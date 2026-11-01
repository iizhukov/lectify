import asyncio
import hashlib
import importlib.util
import io
from pathlib import Path
import os
import shutil
import sys
import threading
from types import SimpleNamespace

root = Path(os.environ['CODEGEN_ROOT'])
source = Path(os.environ['FILE_SOURCE'])
workspace = Path(sys.argv[1])
sys.path.insert(0, str(root / 'utils/codegen/src'))
from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.settings import SettingsGenerator
from generators.services.logger import LoggerGenerator
from generators.services.db import DbGenerator
from generators.services.s3 import S3Generator
from generators.services.grpc_server import GrpcServerGenerator
from generators.services.grpc_client import GrpcClientGenerator
from generators.services.user_auth import UserAuthGenerator
import generators.services.grpc_server as grpc_generator
import yaml

manifest = ServiceManifest.model_validate(yaml.safe_load((source / 'service.yaml').read_text()))
manifest.service.ticket_auth.enabled = False
base.get_settings = lambda: SimpleNamespace(POSTGRES_PORT=5432)
base.get_context_manager = lambda: SimpleNamespace(get_service_context=lambda name: ServiceContext())
grpc_generator.get_service_proto = lambda path: root / 'proto/api/file/index.proto'
for generator in (SettingsGenerator, LoggerGenerator, DbGenerator, S3Generator, GrpcServerGenerator, GrpcClientGenerator, UserAuthGenerator):
    generator(manifest, workspace / 'generated').generate()
shutil.copytree(source / 'src', workspace / 'src')
sys.path.insert(0, str(workspace))
import grpc
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations
from generated.protos.server import index_pb2 as pb
from generated.protos.server import index_pb2_grpc as rpc
from generated.protos.clients.api_auth import index_pb2 as auth_pb
from generated.protos.clients.api_auth import index_pb2_grpc as auth_rpc
from generated.user_auth.interceptor import UserAuthServerInterceptor
from src.service import FileServiceImpl, CHUNK_BYTES
from src.models import StoredFile


class Body(io.BytesIO):
    def __init__(self, data, reads, storage):
        super().__init__(data)
        self.reads = reads
        self.storage = storage
        self.close_calls = 0
    def read(self, size=-1):
        assert 0 < size <= CHUNK_BYTES, 'unbounded object read'
        self.reads.append(size)
        return super().read(size)
    def close(self):
        self.close_calls += 1
        if self.storage.block_close:
            self.storage.close_started.set()
            assert self.storage.close_release.wait(5)
        super().close()


class Storage:
    def __init__(self):
        self.objects = {}
        self.bodies = []
        self.reads = []
        self.fail_put = self.fail_delete = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.block_open = False
        self.open_started = threading.Event()
        self.open_release = threading.Event()
        self.block_close = False
        self.close_started = threading.Event()
        self.close_release = threading.Event()
    def put_stream(self, key, body, content_type):
        data = []
        while True:
            chunk = body.read(CHUNK_BYTES)
            if not chunk:
                break
            data.append(chunk)
        self.objects[key] = b''.join(data)
        if self.block:
            self.started.set()
            assert self.release.wait(5)
        if self.fail_put:
            raise RuntimeError('secret provider credentials')
    def open(self, key):
        if self.block_open:
            self.open_started.set()
            assert self.open_release.wait(5)
        body = Body(self.objects[key], self.reads, self)
        self.bodies.append(body)
        return body
    def delete(self, key):
        if self.fail_delete:
            raise RuntimeError('secret provider credentials')
        self.objects.pop(key, None)


async def denied(call, status):
    try:
        if hasattr(call, '__aiter__'):
            async for _ in call:
                pass
        else:
            await call
    except grpc.aio.AioRpcError as error:
        assert error.code() == status, error
        assert 'secret' not in error.details()
    else:
        raise AssertionError(f'Expected {status}')


def upload(data=b'hello', filename='lecture.txt', declared=None, eof=True, sha256='', sequence=1):
    async def frames():
        current_sequence = sequence
        yield pb.UploadFrame(metadata=pb.UploadMetadata(filename=filename, content_type='text/plain',
            size_bytes=len(data) if declared is None else declared, sha256=sha256))
        if data:
            for offset in range(0, len(data), CHUNK_BYTES):
                last = offset + CHUNK_BYTES >= len(data)
                yield pb.UploadFrame(chunk=data[offset:offset + CHUNK_BYTES], sequence=current_sequence,
                    is_last=eof and last)
                current_sequence += 1
        else:
            yield pb.UploadFrame(chunk=b'', sequence=current_sequence, is_last=eof)
    return frames()


async def main():
    engine = create_async_engine('sqlite+aiosqlite:///' + str(workspace / 'files.db'))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    spec = importlib.util.spec_from_file_location('file_migration', source / 'migrations/versions/0001_add_stored_files.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    def migrate(connection, operation):
        with Operations.context(MigrationContext.configure(connection)):
            operation()
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: migrate(sync, migration.upgrade))
    store = Storage()
    service = FileServiceImpl(factory, store, max_file_bytes=200000, max_upload_seconds=2)
    class Auth(auth_rpc.AuthServiceServicer):
        async def Authenticate(self, request, context):
            if request.access_token not in ('alice', 'bob'):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid')
            return auth_pb.AuthenticateResponse(valid=True, user_id=request.access_token)
    auth_server = grpc.aio.server()
    auth_rpc.add_AuthServiceServicer_to_server(Auth(), auth_server)
    port = auth_server.add_insecure_port('127.0.0.1:0')
    await auth_server.start()
    os.environ['API_FILE_AUTH_ADDRESS'] = f'127.0.0.1:{port}'
    server = grpc.aio.server(interceptors=[UserAuthServerInterceptor()])
    rpc.add_FileServiceServicer_to_server(service, server)
    port = server.add_insecure_port('127.0.0.1:0')
    await server.start()
    channel = grpc.aio.insecure_channel(f'127.0.0.1:{port}')
    stub = rpc.FileServiceStub(channel)
    alice, bob = (('x-user-authorization', 'Bearer alice'),), (('x-user-authorization', 'Bearer bob'),)
    try:
        await denied(stub.ListFiles(pb.ListFilesRequest(), metadata=(('x-user-id', 'alice'),)), grpc.StatusCode.UNAUTHENTICATED)
        data = b'x' * 150000
        file = await stub.Upload(upload(data), metadata=alice)
        assert file.size_bytes == len(data) and file.sha256 == hashlib.sha256(data).hexdigest()
        assert (await stub.GetFile(pb.FileRequest(id=file.id), metadata=alice)).filename == 'lecture.txt'
        for call in (stub.GetFile(pb.FileRequest(id=file.id), metadata=bob),
                     stub.DeleteFile(pb.FileRequest(id=file.id), metadata=bob),
                     stub.Download(pb.FileRequest(id=file.id), metadata=bob)):
            await denied(call, grpc.StatusCode.NOT_FOUND)
        assert not (await stub.ListFiles(pb.ListFilesRequest(), metadata=bob)).files
        frames = [frame async for frame in stub.Download(pb.FileRequest(id=file.id), metadata=alice)]
        assert frames[0].WhichOneof('data') == 'metadata' and frames[-1].is_last
        assert [frame.sequence for frame in frames] == list(range(len(frames)))
        assert b''.join(frame.chunk for frame in frames[1:]) == data
        assert store.bodies[-1].closed and store.reads
        store.block_open = True
        opening = stub.Download(pb.FileRequest(id=file.id), metadata=alice)
        read_task = asyncio.create_task(opening.read())
        assert await asyncio.to_thread(store.open_started.wait, 2)
        opening.cancel()
        store.open_release.set()
        await asyncio.gather(read_task, return_exceptions=True)
        for _ in range(100):
            if len(store.bodies) > 1 and store.bodies[-1].closed:
                break
            await asyncio.sleep(0.01)
        assert len(store.bodies) > 1 and store.bodies[-1].closed
        store.block_open = False
        for args, code in (({'filename': '../escape'}, grpc.StatusCode.INVALID_ARGUMENT),
                           ({'declared': 200001}, grpc.StatusCode.RESOURCE_EXHAUSTED),
                           ({'eof': False}, grpc.StatusCode.INVALID_ARGUMENT),
                           ({'declared': 6}, grpc.StatusCode.INVALID_ARGUMENT),
                           ({'sha256': '0'*64}, grpc.StatusCode.DATA_LOSS),
                           ({'sequence': 2}, grpc.StatusCode.INVALID_ARGUMENT)):
            await denied(stub.Upload(upload(**args), metadata=alice), code)
        assert len(store.objects) == 1
        empty = await stub.Upload(upload(b''), metadata=alice)
        empty_frames = [frame async for frame in stub.Download(pb.FileRequest(id=empty.id), metadata=alice)]
        assert empty_frames[-1].is_last and empty_frames[-1].chunk == b''
        await stub.DeleteFile(pb.FileRequest(id=empty.id), metadata=alice)
        key = next(iter(store.objects))
        store.objects[key] = b'corrupt'
        store.block_close = True
        rejected_download = asyncio.create_task(denied(
            stub.Download(pb.FileRequest(id=file.id), metadata=alice), grpc.StatusCode.DATA_LOSS))
        try:
            assert await asyncio.to_thread(store.close_started.wait,2)
            try:
                await asyncio.wait_for(asyncio.shield(rejected_download),0.05)
            except asyncio.TimeoutError: pass
            else: raise AssertionError('Terminal status preceded storage cleanup')
        finally:
            store.close_release.set()
        await rejected_download
        store.block_close = False
        assert store.bodies[-1].closed
        store.close_started.clear()
        store.close_release.clear()
        store.block_close = True
        class DirectService(FileServiceImpl):
            async def _owner(self, context): return 'alice'
        class Context:
            async def abort(self,*args): raise AssertionError('Cancelled download sent terminal status')
        direct = DirectService(factory,store)
        async def consume():
            async for _ in direct.Download(pb.FileRequest(id=file.id),Context()): pass
        closing_download = asyncio.create_task(consume())
        try:
            assert await asyncio.to_thread(store.close_started.wait,2)
            body = store.bodies[-1]
            for _ in range(2):
                closing_download.cancel()
                await asyncio.sleep(0)
                assert not closing_download.done()
        finally: store.close_release.set()
        result = await asyncio.gather(closing_download,return_exceptions=True)
        assert isinstance(result[0],asyncio.CancelledError)
        assert body.closed and body.close_calls == 1
        store.block_close = False
        store.objects[key] = data
        # A slow incoming producer is bounded independently of a caller's deadline.
        old_timeout = service.max_upload_seconds
        service.max_upload_seconds = 0.05
        async def slow_input():
            yield pb.UploadFrame(metadata=pb.UploadMetadata(filename='slow.txt', size_bytes=1))
            await asyncio.sleep(1)
            yield pb.UploadFrame(chunk=b'x', sequence=1, is_last=True)
        await denied(stub.Upload(slow_input(), metadata=alice), grpc.StatusCode.DEADLINE_EXCEEDED)
        service.max_upload_seconds = old_timeout
        store.fail_put = True
        await denied(stub.Upload(upload(), metadata=alice), grpc.StatusCode.UNAVAILABLE)
        store.fail_put = False
        assert len(store.objects) == 1
        # Cancellation waits for in-flight worker before deleting its object.
        store.block = True
        call = stub.Upload(upload(), metadata=alice)
        assert await asyncio.to_thread(store.started.wait, 2)
        call.cancel()
        store.release.set()
        for _ in range(100):
            async with factory() as session:
                count = await session.scalar(select(func.count()).select_from(StoredFile))
            if count == 1 and len(store.objects) == 1:
                break
            await asyncio.sleep(0.01)
        assert count == 1 and len(store.objects) == 1
        store.block = False
        store.fail_delete = True
        await denied(stub.DeleteFile(pb.FileRequest(id=file.id), metadata=alice), grpc.StatusCode.UNAVAILABLE)
        await denied(stub.GetFile(pb.FileRequest(id=file.id), metadata=alice), grpc.StatusCode.NOT_FOUND)
        store.fail_delete = False
        assert (await stub.DeleteFile(pb.FileRequest(id=file.id), metadata=alice)).deleted
        assert not store.objects
        assert not (await stub.ListFiles(pb.ListFilesRequest(), metadata=alice)).files
    finally:
        await channel.close()
        await server.stop(0)
        await auth_server.stop(0)
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: migrate(sync, migration.downgrade))
        await engine.dispose()

asyncio.run(main())
