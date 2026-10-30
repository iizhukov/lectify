"""Prompt ownership policy and template operations; transport is generated."""
from datetime import datetime, timezone
import re
import uuid

import grpc
from sqlalchemy import delete, or_, select, update

from generated.db.connection import get_session_factory
from generated.grpc_server.grpc_app import PromptServiceBase
from generated.protos.server import index_pb2 as pb
from src.models import Prompt


_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]{0,63})\}\}")
_MAX_TEXT = 65536


class PromptServiceImpl(PromptServiceBase):
    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    def _sessions(self):
        return self._session_factory or get_session_factory()

    async def _principal(self, context):
        # This attribute belongs to the verified server interceptor, never RPC metadata.
        principal = getattr(context, "lectify_principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id or len(user_id) > 128:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Verified user identity required")
        return user_id, getattr(principal, "is_admin", False) is True

    async def _validate(self, context, name, system, template, variables):
        if not name.strip() or len(name) > 200 or not template.strip():
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Name and user template are required")
        if len(system) > _MAX_TEXT or len(template) > _MAX_TEXT:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Prompt text exceeds limit")
        if len(variables) > 100 or len(set(variables)) != len(variables) or any(
                not _VARIABLE.fullmatch(item) for item in variables):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid or duplicate variables")
        placeholders = set(_PLACEHOLDER.findall(system)) | set(_PLACEHOLDER.findall(template))
        if not placeholders.issubset(variables):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Template contains undeclared variables")

    @staticmethod
    def _message(row):
        def timestamp(value):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        return pb.Prompt(id=row.id, owner_id=row.owner_id or "", name=row.name,
            system_prompt=row.system_prompt, user_prompt_template=row.user_prompt_template,
            variables=row.variables, version=row.version, created_at=timestamp(row.created_at),
            updated_at=timestamp(row.updated_at))

    @staticmethod
    def _readable(user_id):
        return or_(Prompt.owner_id.is_(None), Prompt.owner_id == user_id)

    async def _row(self, session, prompt_id, user_id, context):
        row = (await session.execute(select(Prompt).where(
            Prompt.id == prompt_id, self._readable(user_id)))).scalar_one_or_none()
        if row is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Prompt not found")
        return row

    async def _writable(self, row, user_id, admin, context):
        if row.owner_id != user_id and not (row.owner_id is None and admin):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Prompt is read only")

    async def CreatePrompt(self, request, context):
        user_id, admin = await self._principal(context)
        if request.global_prompt and not admin:
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Global prompts require administrator")
        await self._validate(context, request.name, request.system_prompt,
            request.user_prompt_template, list(request.variables))
        now = datetime.now(timezone.utc)
        row = Prompt(id=str(uuid.uuid4()), owner_id=None if request.global_prompt else user_id,
            name=request.name, system_prompt=request.system_prompt,
            user_prompt_template=request.user_prompt_template, variables=list(request.variables),
            version=1, created_at=now, updated_at=now)
        async with self._sessions()() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._message(row)

    async def GetPrompt(self, request, context):
        user_id, _ = await self._principal(context)
        async with self._sessions()() as session:
            return self._message(await self._row(session, request.id, user_id, context))

    async def ListPrompts(self, request, context):
        user_id, _ = await self._principal(context)
        size = request.page_size or 50
        if not 1 <= size <= 100 or not 0 <= request.offset <= 100000:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid pagination")
        async with self._sessions()() as session:
            rows = (await session.execute(select(Prompt).where(self._readable(user_id))
                .order_by(Prompt.created_at, Prompt.id).offset(request.offset).limit(size + 1))).scalars().all()
            return pb.ListPromptsResponse(prompts=[self._message(row) for row in rows[:size]],
                has_more=len(rows) > size)

    async def UpdatePrompt(self, request, context):
        user_id, admin = await self._principal(context)
        if request.expected_version < 1:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "expected_version is required")
        async with self._sessions()() as session:
            row = await self._row(session, request.id, user_id, context)
            await self._writable(row, user_id, admin, context)
            values = {name: getattr(request, name) if request.HasField(name) else getattr(row, name)
                for name in ("name", "system_prompt", "user_prompt_template")}
            values["variables"] = list(request.variables.names) if request.HasField("variables") else row.variables
            await self._validate(context, values["name"], values["system_prompt"],
                values["user_prompt_template"], values["variables"])
            values.update(version=request.expected_version + 1, updated_at=datetime.now(timezone.utc))
            result = await session.execute(update(Prompt).where(Prompt.id == row.id,
                Prompt.version == request.expected_version).values(**values))
            if result.rowcount != 1:
                await context.abort(grpc.StatusCode.ABORTED, "Prompt changed; reload and retry")
            await session.commit()
            await session.refresh(row)
            return self._message(row)

    async def DeletePrompt(self, request, context):
        user_id, admin = await self._principal(context)
        if request.expected_version < 1:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "expected_version is required")
        async with self._sessions()() as session:
            row = await self._row(session, request.id, user_id, context)
            await self._writable(row, user_id, admin, context)
            result = await session.execute(delete(Prompt).where(Prompt.id == row.id,
                Prompt.version == request.expected_version))
            if result.rowcount != 1:
                await context.abort(grpc.StatusCode.ABORTED, "Prompt changed; reload and retry")
            await session.commit()
            return pb.DeletePromptResponse(deleted=True)

    async def RenderPrompt(self, request, context):
        user_id, _ = await self._principal(context)
        async with self._sessions()() as session:
            row = await self._row(session, request.id, user_id, context)
            variables = dict(request.variables)
            if set(variables) != set(row.variables) or any(len(value) > _MAX_TEXT for value in variables.values()):
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Supply exactly the declared variables")
            # Single-pass replacement: inserted values never become new template expressions.
            render = lambda text: _PLACEHOLDER.sub(lambda match: variables[match.group(1)], text)
            rendered_size = sum(len(text) + sum(len(variables[match.group(1)]) - len(match.group(0))
                for match in _PLACEHOLDER.finditer(text))
                for text in (row.system_prompt, row.user_prompt_template))
            if rendered_size > 2 * _MAX_TEXT:
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "Rendered prompt exceeds limit")
            system, user = render(row.system_prompt), render(row.user_prompt_template)
            if len(system) + len(user) > 2 * _MAX_TEXT:
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "Rendered prompt exceeds limit")
            return pb.RenderPromptResponse(system_prompt=system, user_prompt=user)
