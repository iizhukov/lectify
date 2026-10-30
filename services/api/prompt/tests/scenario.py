import asyncio
from pathlib import Path
import os
import shutil
import sys
from types import SimpleNamespace

root = Path(os.environ['LECTIFY_ROOT'])
source = Path(os.environ['PROMPT_SOURCE'])
workspace = Path(sys.argv[1])
sys.path.insert(0, str(root / 'utils/codegen/src'))
from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.settings import SettingsGenerator
from generators.services.logger import LoggerGenerator
from generators.services.db import DbGenerator
from generators.services.grpc_server import GrpcServerGenerator
from generators.services.grpc_client import GrpcClientGenerator
from generators.services.user_auth import UserAuthGenerator
import generators.services.grpc_server as grpc_generator
import yaml

manifest = ServiceManifest.model_validate(yaml.safe_load((source / 'service.yaml').read_text()))
# Exercise user identity without requiring a live TAS in this isolated test.
# Production keeps ticket_auth enabled and authenticates the calling service separately.
manifest.service.ticket_auth.enabled = False
# Generate only the components used by this service, in a temporary checkout.
base.get_settings = lambda: SimpleNamespace(POSTGRES_PORT=5432)
base.get_context_manager = lambda: SimpleNamespace(get_service_context=lambda name: ServiceContext())
grpc_generator.get_service_proto = lambda path: root / 'proto/api/prompt/index.proto'
for generator in (SettingsGenerator, LoggerGenerator, DbGenerator, GrpcServerGenerator, GrpcClientGenerator, UserAuthGenerator):
    generator(manifest, workspace / 'generated').generate()
shutil.copytree(source / 'src', workspace / 'src')
sys.path.insert(0, str(workspace))

import grpc
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from generated.db.base import BaseModel
from generated.protos.server import index_pb2 as pb
from generated.protos.server import index_pb2_grpc as rpc
from src.service import PromptServiceImpl
from generated.user_auth.interceptor import UserAuthServerInterceptor
from generated.protos.clients.api_auth import index_pb2 as auth_pb
from generated.protos.clients.api_auth import index_pb2_grpc as auth_rpc


class TrustedContext:
    def __init__(self, context, principal):
        self.context = context
        self.lectify_principal = principal

    def __getattr__(self, name):
        return getattr(self.context, name)


async def denied(awaitable, status):
    try:
        await awaitable
    except grpc.aio.AioRpcError as error:
        assert error.code() == status, error
    else:
        raise AssertionError(f'Expected {status}')


async def main():
    engine = create_async_engine('sqlite+aiosqlite:///' + str(workspace / 'prompts.db'))
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('prompt_migration', source / 'migrations/versions/0001_add_prompts.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    def migrate(connection, operation):
        with Operations.context(MigrationContext.configure(connection)):
            operation()
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: migrate(sync, migration.upgrade))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = PromptServiceImpl(factory)

    # A real generated boundary calls the test auth backend over gRPC.
    identities = {'alice-ticket': SimpleNamespace(user_id='alice', is_admin=False),
                  'bob-ticket': SimpleNamespace(user_id='bob', is_admin=False),
                  'admin-ticket': SimpleNamespace(user_id='admin', is_admin=True)}
    class Auth(auth_rpc.AuthServiceServicer):
        async def Authenticate(self, request, context):
            principal = identities.get(request.access_token)
            if principal is None:
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid session')
            return auth_pb.AuthenticateResponse(valid=True, user_id=principal.user_id, is_admin=principal.is_admin)
    auth_server = grpc.aio.server()
    auth_rpc.add_AuthServiceServicer_to_server(Auth(), auth_server)
    auth_port = auth_server.add_insecure_port('127.0.0.1:0')
    await auth_server.start()
    os.environ['API_PROMPT_AUTH_ADDRESS'] = f'127.0.0.1:{auth_port}'
    server = grpc.aio.server(interceptors=[UserAuthServerInterceptor()])
    rpc.add_PromptServiceServicer_to_server(service, server)
    port = server.add_insecure_port('127.0.0.1:0')
    await server.start()
    channel = grpc.aio.insecure_channel(f'127.0.0.1:{port}')
    stub = rpc.PromptServiceStub(channel)
    alice = (('x-user-authorization', 'Bearer alice-ticket'),)
    bob = (('x-user-authorization', 'Bearer bob-ticket'),)
    admin = (('x-user-authorization', 'Bearer admin-ticket'),)
    try:
        await denied(stub.ListPrompts(pb.ListPromptsRequest(), metadata=(('x-user-id', 'alice'),)), grpc.StatusCode.UNAUTHENTICATED)
        prompt = await stub.CreatePrompt(pb.CreatePromptRequest(name='Lecture',
            system_prompt='Topic {{topic}}', user_prompt_template='Summarize {{text}}',
            variables=['topic', 'text']), metadata=alice)
        assert prompt.owner_id == 'alice' and prompt.version == 1
        await denied(stub.GetPrompt(pb.GetPromptRequest(id=prompt.id), metadata=bob), grpc.StatusCode.NOT_FOUND)
        await denied(stub.UpdatePrompt(pb.UpdatePromptRequest(id=prompt.id, expected_version=1, name='stolen'), metadata=bob), grpc.StatusCode.NOT_FOUND)
        await denied(stub.DeletePrompt(pb.DeletePromptRequest(id=prompt.id, expected_version=1), metadata=bob), grpc.StatusCode.NOT_FOUND)
        result = await stub.RenderPrompt(pb.RenderPromptRequest(id=prompt.id,
            variables={'topic': '{{text}}', 'text': 'notes'}), metadata=alice)
        assert result.system_prompt == 'Topic {{text}}' and result.user_prompt == 'Summarize notes'
        await denied(stub.RenderPrompt(pb.RenderPromptRequest(id=prompt.id, variables={'text': 'notes'}), metadata=alice), grpc.StatusCode.INVALID_ARGUMENT)
        await denied(stub.CreatePrompt(pb.CreatePromptRequest(name='Bad', user_prompt_template='{{secret}}'), metadata=alice), grpc.StatusCode.INVALID_ARGUMENT)
        await denied(stub.CreatePrompt(pb.CreatePromptRequest(name='Global', user_prompt_template='Hello', global_prompt=True), metadata=alice), grpc.StatusCode.PERMISSION_DENIED)
        shared = await stub.CreatePrompt(pb.CreatePromptRequest(name='Global', user_prompt_template='Shared', global_prompt=True), metadata=admin)
        assert shared.owner_id == ''
        assert (await stub.GetPrompt(pb.GetPromptRequest(id=shared.id), metadata=bob)).name == 'Global'
        await denied(stub.UpdatePrompt(pb.UpdatePromptRequest(id=shared.id, expected_version=1, name='Edit'), metadata=alice), grpc.StatusCode.PERMISSION_DENIED)
        page = await stub.ListPrompts(pb.ListPromptsRequest(page_size=1), metadata=alice)
        assert len(page.prompts) == 1 and page.has_more
        assert len((await stub.ListPrompts(pb.ListPromptsRequest(), metadata=bob)).prompts) == 1
        updated = await stub.UpdatePrompt(pb.UpdatePromptRequest(id=prompt.id, expected_version=1,
            system_prompt=''), metadata=alice)
        assert updated.system_prompt == '' and updated.version == 2
        await denied(stub.UpdatePrompt(pb.UpdatePromptRequest(id=prompt.id, expected_version=1, name='stale'), metadata=alice), grpc.StatusCode.ABORTED)
        raced = await stub.CreatePrompt(pb.CreatePromptRequest(name='Race', user_prompt_template='Hello'), metadata=alice)
        outcomes = await asyncio.gather(*(
            stub.UpdatePrompt(pb.UpdatePromptRequest(id=raced.id, expected_version=1, name=name), metadata=alice)
            for name in ('First', 'Second')), return_exceptions=True)
        assert sum(isinstance(item, pb.Prompt) for item in outcomes) == 1
        failures = [item for item in outcomes if isinstance(item, grpc.aio.AioRpcError)]
        assert len(failures) == 1 and failures[0].code() == grpc.StatusCode.ABORTED
        # A fresh instance sees committed data: state does not live in the handler.
        replica = PromptServiceImpl(factory)
        context = TrustedContext(None, identities['alice-ticket'])
        assert (await replica.GetPrompt(pb.GetPromptRequest(id=prompt.id), context)).version == 2
        oversized = await stub.CreatePrompt(pb.CreatePromptRequest(name='Bounded', user_prompt_template='{{x}}' * 100,
            variables=['x']), metadata=alice)
        await denied(stub.RenderPrompt(pb.RenderPromptRequest(id=oversized.id, variables={'x': 'z' * 65536}), metadata=alice), grpc.StatusCode.RESOURCE_EXHAUSTED)
        await denied(stub.DeletePrompt(pb.DeletePromptRequest(id=prompt.id, expected_version=1), metadata=alice), grpc.StatusCode.ABORTED)
        assert (await stub.DeletePrompt(pb.DeletePromptRequest(id=prompt.id, expected_version=2), metadata=alice)).deleted
        await denied(stub.GetPrompt(pb.GetPromptRequest(id=prompt.id), metadata=alice), grpc.StatusCode.NOT_FOUND)
    finally:
        await channel.close()
        await server.stop(0)
        await auth_server.stop(0)
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: migrate(sync, migration.downgrade))
        await engine.dispose()

asyncio.run(main())
