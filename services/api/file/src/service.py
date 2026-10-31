"""Ownership and file lifecycle; transport, DB and object client are generated."""
import asyncio
from datetime import timezone
import hashlib
import re
import tempfile
import time
import uuid

import grpc
from sqlalchemy import delete, select

from generated.db.connection import get_session_factory
from generated.grpc_server.grpc_app import FileServiceBase
from generated.protos.server import index_pb2 as pb
from generated.s3.s3 import get_user_files_client
from src.models import StoredFile


CHUNK_BYTES = 65536


async def _io(function, *args):
    """Do not close a file/response while its worker thread is still using it."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def _open_object(function, key):
    """Close a late-acquired response if cancellation wins the acquisition race."""
    task = asyncio.create_task(asyncio.to_thread(function, key))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        result = await asyncio.gather(task, return_exceptions=True)
        if not isinstance(result[0], BaseException):
            await _io(result[0].close)
        raise


class FileServiceImpl(FileServiceBase):
    def __init__(self, session_factory=None, storage=None, max_file_bytes=268435456, max_upload_seconds=300):
        if max_file_bytes < 1 or max_upload_seconds <= 0:
            raise ValueError('File limits must be positive')
        self._factory = session_factory
        self._storage = storage
        self.max_file_bytes = max_file_bytes
        self.max_upload_seconds = max_upload_seconds

    def _sessions(self):
        return self._factory or get_session_factory()

    def _objects(self):
        if self._storage is None:
            self._storage = get_user_files_client()
        return self._storage

    async def _owner(self, context):
        owner = getattr(getattr(context, 'lectify_principal', None), 'user_id', None)
        if not isinstance(owner, str) or not owner or len(owner) > 128:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Verified user identity required')
        return owner

    @staticmethod
    def _message(row):
        created = row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return pb.File(id=row.id, filename=row.filename, content_type=row.content_type,
            size_bytes=row.size_bytes, sha256=row.sha256, created_at=created.isoformat())

    async def _row(self, session, file_id, owner, context, ready=True):
        statement = select(StoredFile).where(StoredFile.id == file_id, StoredFile.owner_id == owner)
        if ready:
            statement = statement.where(StoredFile.state == 'READY')
        row = (await session.execute(statement)).scalar_one_or_none()
        if row is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, 'File not found')
        return row

    async def Upload(self, request_iterator, context):
        owner = await self._owner(context)
        iterator = request_iterator.__aiter__()
        deadline = time.monotonic() + self.max_upload_seconds
        async def next_frame():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, 'Upload deadline exceeded')
            try:
                return await asyncio.wait_for(anext(iterator), remaining)
            except asyncio.TimeoutError:
                await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, 'Upload deadline exceeded')
        try:
            first = await next_frame()
        except StopAsyncIteration:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Upload metadata is required')
        if first.WhichOneof('data') != 'metadata' or first.sequence != 0 or first.is_last:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Upload starts with metadata')
        metadata = first.metadata
        if (not metadata.filename.strip() or len(metadata.filename) > 255
                or metadata.filename in ('.', '..') or any(char in metadata.filename for char in '/\\')
                or any(ord(char) < 32 or ord(char) == 127 for char in metadata.filename)):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid filename')
        content_type = metadata.content_type or 'application/octet-stream'
        if len(content_type) > 128 or not re.fullmatch(r'[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+', content_type):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid content type')
        if not 0 <= metadata.size_bytes <= self.max_file_bytes:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'File exceeds size limit')
        if metadata.sha256 and not re.fullmatch('[a-f0-9]{64}', metadata.sha256):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid SHA256 digest')
        digest, size, sequence, closed = hashlib.sha256(), 0, 1, False
        with tempfile.SpooledTemporaryFile(max_size=1048576, mode='w+b') as body:
            while True:
                try:
                    frame = await next_frame()
                except StopAsyncIteration:
                    break
                if closed or frame.WhichOneof('data') != 'chunk' or frame.sequence != sequence:
                    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid upload sequence')
                sequence += 1
                if len(frame.chunk) > CHUNK_BYTES or size + len(frame.chunk) > metadata.size_bytes:
                    await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Upload chunk exceeds declared limit')
                body.write(frame.chunk)
                digest.update(frame.chunk)
                size += len(frame.chunk)
                closed = frame.is_last
            if not closed or size != metadata.size_bytes:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Upload requires EOF and exact size')
            checksum = digest.hexdigest()
            if metadata.sha256 and metadata.sha256 != checksum:
                await context.abort(grpc.StatusCode.DATA_LOSS, 'Upload checksum mismatch')
            file_id = str(uuid.uuid4())
            row = StoredFile(id=file_id, owner_id=owner, object_key='uploads/' + file_id,
                filename=metadata.filename, content_type=content_type, size_bytes=size,
                sha256=checksum, state='PENDING')
            async with self._sessions()() as session:
                session.add(row)
                await session.commit()
            body.seek(0)
            try:
                await _io(self._objects().put_stream, row.object_key, body, content_type)
                async with self._sessions()() as session:
                    persisted = await self._row(session, file_id, owner, context, ready=False)
                    persisted.state = 'READY'
                    await session.commit()
                    await session.refresh(persisted)
                    return self._message(persisted)
            except BaseException as error:
                # A durable PENDING row remains if cleanup itself fails, never visible as READY.
                try:
                    await _io(self._objects().delete, row.object_key)
                    async with self._sessions()() as session:
                        await session.execute(delete(StoredFile).where(StoredFile.id == file_id))
                        await session.commit()
                except Exception:
                    pass
                if isinstance(error, asyncio.CancelledError):
                    raise
                await context.abort(grpc.StatusCode.UNAVAILABLE, 'File storage unavailable')

    async def GetFile(self, request, context):
        owner = await self._owner(context)
        async with self._sessions()() as session:
            return self._message(await self._row(session, request.id, owner, context))

    async def ListFiles(self, request, context):
        owner = await self._owner(context)
        size = request.page_size or 50
        if not 1 <= size <= 100 or not 0 <= request.offset <= 100000:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid pagination')
        async with self._sessions()() as session:
            rows = (await session.execute(select(StoredFile).where(StoredFile.owner_id == owner,
                StoredFile.state == 'READY').order_by(StoredFile.created_at, StoredFile.id)
                .offset(request.offset).limit(size + 1))).scalars().all()
            return pb.ListFilesResponse(files=[self._message(row) for row in rows[:size]], has_more=len(rows) > size)

    async def Download(self, request, context):
        owner = await self._owner(context)
        async with self._sessions()() as session:
            row = await self._row(session, request.id, owner, context)
            metadata, key = self._message(row), row.object_key
        response = None
        closing = None
        async def close_response():
            nonlocal response, closing
            if closing is None and response is not None:
                closing = asyncio.create_task(_io(response.close))
                response = None
            if closing is None:
                return
            cancelled = False
            while not closing.done():
                try:
                    await asyncio.shield(closing)
                except asyncio.CancelledError:
                    cancelled = True
            closing.result()
            if cancelled:
                raise asyncio.CancelledError

        async def fail(code, message):
            # Complete storage cleanup before publishing a terminal RPC status.
            await close_response()
            await context.abort(code, message)

        try:
            try:
                response = await _open_object(self._objects().open, key)
            except Exception:
                await context.abort(grpc.StatusCode.UNAVAILABLE, 'File storage unavailable')
            yield pb.DownloadFrame(metadata=metadata, sequence=0)
            size, sequence, digest = 0, 1, hashlib.sha256()
            while True:
                try:
                    data = await _io(response.read, CHUNK_BYTES)
                except Exception:
                    await fail(grpc.StatusCode.UNAVAILABLE, 'File storage unavailable')
                if not data:
                    break
                size += len(data)
                if len(data) > CHUNK_BYTES or size > metadata.size_bytes:
                    await fail(grpc.StatusCode.DATA_LOSS, 'Stored file exceeds metadata size')
                digest.update(data)
                yield pb.DownloadFrame(chunk=data, sequence=sequence)
                sequence += 1
            if size != metadata.size_bytes or digest.hexdigest() != metadata.sha256:
                await fail(grpc.StatusCode.DATA_LOSS, 'Stored file checksum mismatch')
            await close_response()
            yield pb.DownloadFrame(chunk=b'', sequence=sequence, is_last=True)
        finally:
            await close_response()

    async def DeleteFile(self, request, context):
        owner = await self._owner(context)
        async with self._sessions()() as session:
            row = await self._row(session, request.id, owner, context, ready=False)
            if row.state == 'PENDING':
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION, 'File is not ready')
            row.state = 'DELETING'
            key = row.object_key
            await session.commit()
        try:
            await _io(self._objects().delete, key)
        except Exception:
            await context.abort(grpc.StatusCode.UNAVAILABLE, 'File storage unavailable')
        async with self._sessions()() as session:
            await session.execute(delete(StoredFile).where(StoredFile.id == request.id, StoredFile.owner_id == owner))
            await session.commit()
        return pb.DeleteFileResponse(deleted=True)
