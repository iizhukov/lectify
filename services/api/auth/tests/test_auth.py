"""Generate a temporary checkout, then exercise real async SQLite business state."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
SERVICE = Path(__file__).resolve().parents[1]

GENERATE = r'''
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.settings import SettingsGenerator
from generators.services.logger import LoggerGenerator
from generators.services.db import DbGenerator
from generators.services.grpc_server import GrpcServerGenerator
import yaml
manifest = ServiceManifest.model_validate(yaml.safe_load(Path('service.yaml').read_text()))
base.get_settings = lambda: SimpleNamespace(POSTGRES_PORT=5432)
base.get_context_manager = lambda: SimpleNamespace(get_service_context=lambda name: ServiceContext())
for generator in (SettingsGenerator, LoggerGenerator, DbGenerator, GrpcServerGenerator):
    generator(manifest, Path('generated').resolve()).generate()
'''

SCENARIO = r'''
import asyncio
from pathlib import Path
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import grpc
from generated.db.base import BaseModel
from generated.protos.server import index_pb2 as pb
from src.models import User, Session, PasswordReset, ResetDelivery
from src.service import AuthServiceImpl

class Error(Exception):
    def __init__(self, code, details):
        self.code, self.details = code, details

class Context:
    async def abort(self, code, details):
        raise Error(code, details)

context = Context()

async def reject(awaitable, code=grpc.StatusCode.UNAUTHENTICATED):
    try:
        await awaitable
    except Error as error:
        assert error.code == code, (error.code, error.details)
        return error.details
    raise AssertionError('Expected authorization failure')

async def main():
    engine = create_async_engine('sqlite+aiosqlite:///auth.sqlite')
    factory = async_sessionmaker(engine, expire_on_commit=False)
    def migrate(connection):
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        for path in sorted(Path('migrations/versions').glob('*.py')):
            spec = importlib.util.spec_from_file_location(path.stem, path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
    async with engine.begin() as connection:
        await connection.run_sync(migrate)
    delivered = []
    async def send(email, token):
        delivered.append((email, token))
    now = [10000]
    from cryptography.fernet import Fernet
    delivery_key = Fernet.generate_key()
    first = AuthServiceImpl(session_factory=factory, reset_delivery=send, reset_delivery_key=delivery_key, clock=lambda: now[0])
    second = AuthServiceImpl(session_factory=factory, reset_delivery=send, reset_delivery_key=delivery_key, clock=lambda: now[0])
    request = pb.RegisterRequest(username='Alice', email='ALICE@example.org',
        password='Strong password 1!', full_name='Alice')
    login = await first.Register(request, context)
    assert login.principal.username == 'alice' and not login.principal.is_admin
    assert login.access_token != login.refresh_token
    verified = await second.Authenticate(pb.AuthenticateRequest(access_token=login.access_token), context)
    assert verified.access_expires_at == login.access_expires_at
    assert verified.valid and verified.user_id == login.principal.user_id
    await reject(first.Authenticate(pb.AuthenticateRequest(access_token=login.refresh_token), context))
    await reject(first.Register(request, context), grpc.StatusCode.ALREADY_EXISTS)
    absent = await reject(first.Login(pb.LoginRequest(username='missing', password='wrong'), context))
    wrong = await reject(first.Login(pb.LoginRequest(username='Alice', password='wrong'), context))
    assert absent == wrong
    async with factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        sessions = (await session.execute(select(Session))).scalars().all()
        assert user.password_hash != request.password and request.password not in user.password_hash
        assert len(sessions) == 1
        assert sessions[0].access_hash != login.access_token and sessions[0].refresh_hash != login.refresh_token
    rotated = await second.Refresh(pb.TokenRequest(token=login.refresh_token), context)
    await reject(first.Refresh(pb.TokenRequest(token=login.refresh_token), context))
    await reject(first.Authenticate(pb.AuthenticateRequest(access_token=login.access_token), context))
    assert (await first.Authenticate(pb.AuthenticateRequest(access_token=rotated.access_token), context)).valid
    await second.Logout(pb.TokenRequest(token=rotated.access_token), context)
    await reject(first.Refresh(pb.TokenRequest(token=rotated.refresh_token), context))
    # Single winner for simultaneous replay, across independent handler instances.
    login = await first.Login(pb.LoginRequest(username='alice', password=request.password), context)
    results = await asyncio.gather(
        first.Refresh(pb.TokenRequest(token=login.refresh_token), context),
        second.Refresh(pb.TokenRequest(token=login.refresh_token), context), return_exceptions=True)
    assert sum(isinstance(item, pb.AuthResponse) for item in results) == 1
    assert sum(isinstance(item, Error) for item in results) == 1
    login = await first.Login(pb.LoginRequest(username='alice', password=request.password), context)
    await reject(second.ChangePassword(pb.ChangePasswordRequest(access_token=login.access_token,
        current_password='wrong', new_password='Changed password 2!'), context))
    await second.ChangePassword(pb.ChangePasswordRequest(access_token=login.access_token,
        current_password=request.password, new_password='Changed password 2!'), context)
    await reject(first.Authenticate(pb.AuthenticateRequest(access_token=login.access_token), context))
    await reject(first.Refresh(pb.TokenRequest(token=login.refresh_token), context))
    await reject(first.Login(pb.LoginRequest(username='alice', password=request.password), context))
    login = await first.Login(pb.LoginRequest(username='alice', password='Changed password 2!'), context)
    await reject(AuthServiceImpl(session_factory=factory).RequestPasswordReset(
        pb.PasswordResetRequest(email='unknown@example.org'), context), grpc.StatusCode.UNAVAILABLE)
    assert (await first.RequestPasswordReset(pb.PasswordResetRequest(email='unknown@example.org'), context)).accepted
    assert delivered == []
    await first.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context)
    assert delivered == []  # accepting known email never awaits a mail provider
    assert (await second.deliver_password_resets()) == {'delivered': 1, 'failed': 0}
    email, token = delivered[-1]
    async with factory() as session:
        stored = (await session.execute(select(PasswordReset))).scalar_one()
        assert stored.token_hash != token and token not in stored.token_hash
    await second.ResetPassword(pb.ResetPasswordRequest(token=token, new_password='Reset password 3!'), context)
    await reject(first.ResetPassword(pb.ResetPasswordRequest(token=token, new_password='Reset password 4!'), context))
    await reject(first.Authenticate(pb.AuthenticateRequest(access_token=login.access_token), context))
    await reject(first.Refresh(pb.TokenRequest(token=login.refresh_token), context))
    login = await first.Login(pb.LoginRequest(username='alice', password='Reset password 3!'), context)
    now[0] += 901
    await reject(second.Authenticate(pb.AuthenticateRequest(access_token=login.access_token), context))
    login = await second.Refresh(pb.TokenRequest(token=login.refresh_token), context)
    now[0] += 7 * 24 * 3600 + 1
    await reject(first.Refresh(pb.TokenRequest(token=login.refresh_token), context))
    await first.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context)
    await second.deliver_password_resets()
    now[0] += 3601
    await reject(first.ResetPassword(pb.ResetPasswordRequest(token=delivered[-1][1], new_password='Another password 4!'), context))
    await engine.dispose()

asyncio.run(main())
'''


@pytest.fixture
def generated_service(tmp_path):
    project = tmp_path / 'project'
    service = project / 'services/api/auth'
    service.mkdir(parents=True)
    shutil.copytree(SERVICE / 'src', service / 'src')
    shutil.copytree(SERVICE / 'migrations', service / 'migrations')
    shutil.copy(SERVICE / 'service.yaml', service / 'service.yaml')
    protocol = project / 'proto/api/auth'
    protocol.mkdir(parents=True)
    shutil.copy(ROOT / 'proto/api/auth/index.proto', protocol / 'index.proto')
    environment = dict(os.environ, CODEGEN_ROOT=str(project), PYTHONPATH=str(service))
    generated = subprocess.run(
        [sys.executable, '-c', GENERATE, str(ROOT / 'utils/codegen/src')], cwd=service,
        env=environment, text=True, capture_output=True, timeout=30,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    return service, environment


def test_auth_persistence_and_security(generated_service):
    service, environment = generated_service
    result = subprocess.run([sys.executable, '-c', SCENARIO], cwd=service, env=environment,
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr

RPC_SCENARIO = r'''
import asyncio
import grpc
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from generated.db.base import BaseModel
from generated.protos.server import index_pb2 as pb
from generated.protos.server import index_pb2_grpc as rpc
from src.service import AuthServiceImpl

async def expect_error(awaitable, code):
    try:
        await awaitable
    except grpc.aio.AioRpcError as error:
        assert error.code() == code, error
        return
    raise AssertionError('Expected RPC failure')

async def main():
    engine = create_async_engine('sqlite+aiosqlite:///rpc-auth.sqlite')
    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    server = grpc.aio.server()
    rpc.add_AuthServiceServicer_to_server(
        AuthServiceImpl(session_factory=async_sessionmaker(engine, expire_on_commit=False)), server,
    )
    port = server.add_insecure_port('127.0.0.1:0')
    assert port
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f'127.0.0.1:{port}') as channel:
            client = rpc.AuthServiceStub(channel)
            await expect_error(client.Authenticate(pb.AuthenticateRequest(access_token='forged'), timeout=5),
                               grpc.StatusCode.UNAUTHENTICATED)
            await expect_error(client.Register(pb.RegisterRequest(username='bob', email='bob@example.org',
                password='short'), timeout=5), grpc.StatusCode.INVALID_ARGUMENT)
            account = await client.Register(pb.RegisterRequest(username='bob', email='bob@example.org',
                password='Strong password 1!'), timeout=5)
            verified = await client.Authenticate(pb.AuthenticateRequest(access_token=account.access_token), timeout=5)
            assert verified.valid and verified.user_id == account.principal.user_id
            rotated = await client.Refresh(pb.TokenRequest(token=account.refresh_token), timeout=5)
            await expect_error(client.Authenticate(pb.AuthenticateRequest(access_token=account.access_token), timeout=5),
                               grpc.StatusCode.UNAUTHENTICATED)
            await client.Logout(pb.TokenRequest(token=rotated.refresh_token), timeout=5)
            await expect_error(client.Authenticate(pb.AuthenticateRequest(access_token=rotated.access_token), timeout=5),
                               grpc.StatusCode.UNAUTHENTICATED)
    finally:
        await server.stop(0)
        await engine.dispose()

asyncio.run(main())
'''


def test_auth_real_rpc_boundary(generated_service):
    service, environment = generated_service
    result = subprocess.run([sys.executable, '-c', RPC_SCENARIO], cwd=service, env=environment,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

OUTBOX_SCENARIO = SCENARIO[:SCENARIO.index('async def main():')] + r'''
async def main():
    from cryptography.fernet import Fernet
    engine = create_async_engine('sqlite+aiosqlite:///reset-outbox.sqlite')
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    now = [10000]
    started, release = asyncio.Event(), asyncio.Event()
    delivered = []
    key = Fernet.generate_key()
    async def blocked_delivery(email, token):
        started.set()
        await release.wait()
        delivered.append((email, token))
    first = AuthServiceImpl(session_factory=factory, reset_delivery=blocked_delivery,
        reset_delivery_key=key, clock=lambda: now[0])
    second = AuthServiceImpl(session_factory=factory, reset_delivery=blocked_delivery,
        reset_delivery_key=key, clock=lambda: now[0])
    await first.Register(pb.RegisterRequest(username='alice', email='alice@example.org',
        password='Strong password 1!'), context)
    known = await asyncio.wait_for(first.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context), 1)
    unknown = await asyncio.wait_for(first.RequestPasswordReset(pb.PasswordResetRequest(email='unknown@example.org'), context), 1)
    assert known == unknown and known.accepted
    assert not started.is_set()  # no callback on either public request path
    await asyncio.gather(
        first.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context),
        second.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context))
    async with factory() as session:
        rows = (await session.execute(select(ResetDelivery))).scalars().all()
        assert len(rows) == 1
        ciphertext = rows[0].token_ciphertext
        token = Fernet(key).decrypt(ciphertext).decode()
        assert token.encode() not in ciphertext
        assert rows[0].reset_hash != token
        assert key not in ciphertext
    work = asyncio.create_task(first.deliver_password_resets())
    await asyncio.wait_for(started.wait(), 2)
    assert await second.deliver_password_resets() == {'delivered': 0, 'failed': 0}
    # Aborted worker leaves a durable lease, not a lost or acknowledged message.
    work.cancel()
    try:
        await work
    except asyncio.CancelledError:
        pass
    assert await second.deliver_password_resets() == {'delivered': 0, 'failed': 0}
    now[0] += 31
    release.set()
    assert await second.deliver_password_resets() == {'delivered': 1, 'failed': 0}
    assert delivered == [('alice@example.org', token)]
    async with factory() as session:
        row = (await session.execute(select(ResetDelivery))).scalar_one()
        assert row.token_ciphertext == b'' and row.delivered_at == now[0]
    assert await first.deliver_password_resets() == {'delivered': 0, 'failed': 0}
    await first.ResetPassword(pb.ResetPasswordRequest(token=token, new_password='Changed password 2!'), context)
    async with factory() as session:
        assert (await session.execute(select(ResetDelivery))).first() is None
    # Failed callback times out; retry preserves exactly the same token.
    async def never_returns(email, token):
        await asyncio.Event().wait()
    failing = AuthServiceImpl(session_factory=factory, reset_delivery=never_returns,
        reset_delivery_key=key, clock=lambda: now[0])
    await failing.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context)
    result = await asyncio.wait_for(failing.deliver_password_resets(timeout=0.02, lease_seconds=10), 1)
    assert result == {'delivered': 0, 'failed': 1}
    async with factory() as session:
        row = (await session.execute(select(ResetDelivery))).scalar_one()
        retry_ciphertext = row.token_ciphertext
        assert row.attempts == 1 and row.delivered_at is None
    now[0] += 61
    wrong_key = AuthServiceImpl(session_factory=factory, reset_delivery=blocked_delivery,
        reset_delivery_key=Fernet.generate_key(), clock=lambda: now[0])
    assert await wrong_key.deliver_password_resets() == {'delivered': 0, 'failed': 1}
    assert len(delivered) == 1
    now[0] += 61
    assert await first.deliver_password_resets() == {'delivered': 1, 'failed': 0}
    assert delivered[-1][1] == Fernet(key).decrypt(retry_ciphertext).decode()
    # Sender exceptions are not copied to API, stdout or database error fields.
    # Expired deliveries never call the adapter.
    await first.ResetPassword(pb.ResetPasswordRequest(token=delivered[-1][1], new_password='Changed password 3!'), context)
    await first.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context)
    now[0] += 3601
    assert await first.deliver_password_resets() == {'delivered': 0, 'failed': 0}
    assert len(delivered) == 2
    await engine.dispose()

asyncio.run(main())
'''


def test_reset_outbox_is_durable_encrypted_bounded_and_replica_safe(generated_service):
    service, environment = generated_service
    result = subprocess.run([sys.executable, '-c', OUTBOX_SCENARIO], cwd=service, env=environment,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

MIGRATION_SCENARIO = r'''
import importlib.util
from pathlib import Path
from sqlalchemy import create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
from generated.db.base import BaseModel
from src import models

engine = create_engine('sqlite:///migration.sqlite')
migrations = []
for path in sorted(Path('migrations/versions').glob('*.py')):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    migrations.append(module)
with engine.begin() as connection:
    with Operations.context(MigrationContext.configure(connection)):
        for migration in migrations:
            migration.upgrade()
        for name, table in BaseModel.metadata.tables.items():
            columns = {column['name'] for column in inspect(connection).get_columns(name)}
            assert columns == set(table.columns.keys()), (name, columns)
        for migration in reversed(migrations):
            migration.downgrade()
        assert not any(name.startswith('auth_') for name in inspect(connection).get_table_names())
        for migration in migrations:
            migration.upgrade()
engine.dispose()
'''


def test_auth_migrations_upgrade_downgrade_and_model_parity(generated_service):
    service, environment = generated_service
    result = subprocess.run([sys.executable, '-c', MIGRATION_SCENARIO], cwd=service, env=environment,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

RESET_RACE_SCENARIO = SCENARIO[:SCENARIO.index('async def main():')] + r'''
async def main():
    from cryptography.fernet import Fernet
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.service import token_hash
    engine = create_async_engine('sqlite+aiosqlite:///reset-race.sqlite')
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    key = Fernet.generate_key()
    now = [10000]
    delivered = []
    async def send(email, token):
        delivered.append(token)
    normal = AuthServiceImpl(session_factory=factory, reset_delivery=send,
        reset_delivery_key=key, clock=lambda: now[0])
    registered = await normal.Register(pb.RegisterRequest(username='alice', email='alice@example.org',
        password='Strong password 1!'), context)
    selected, resume = asyncio.Event(), asyncio.Event()
    class PausingSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            result = await super().execute(statement, *args, **kwargs)
            if 'WHERE auth_users.email =' in str(statement) and not selected.is_set():
                selected.set()
                await resume.wait()
            return result
    paused_factory = async_sessionmaker(engine, class_=PausingSession, expire_on_commit=False)
    stale = AuthServiceImpl(session_factory=paused_factory, reset_delivery=send,
        reset_delivery_key=key, clock=lambda: now[0])
    task = asyncio.create_task(stale.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context))
    await asyncio.wait_for(selected.wait(), 2)
    await normal.ChangePassword(pb.ChangePasswordRequest(access_token=registered.access_token,
        current_password='Strong password 1!', new_password='Changed password 2!'), context)
    resume.set()
    assert (await task).accepted
    async with factory() as session:
        assert (await session.execute(select(ResetDelivery))).first() is None
    await normal.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context)
    assert await normal.deliver_password_resets() == {'delivered': 1, 'failed': 0}
    assert len(delivered) == 1
    # Historical stale reset/outbox rows must not block a fresh valid request.
    async with factory() as session:
        await session.execute(delete(ResetDelivery))
        await session.execute(delete(PasswordReset))
        user = (await session.execute(select(User))).scalar_one()
        stale_token = 'pr_stale_token'
        digest = token_hash(stale_token)
        session.add(PasswordReset(token_hash=digest, user_id=user.id,
            expires_at=now[0]+3600, security_version=0))
        await session.flush()
        session.add(ResetDelivery(id='historical-stale', user_id=user.id, reset_hash=digest,
            token_ciphertext=Fernet(key).encrypt(stale_token.encode()), due_at=now[0],
            lease_until=0, lease_owner='', attempts=0))
        await session.commit()
    await normal.RequestPasswordReset(pb.PasswordResetRequest(email='alice@example.org'), context)
    async with factory() as session:
        reset = (await session.execute(select(PasswordReset))).scalar_one()
        assert reset.security_version == 1 and reset.token_hash != digest
    assert await normal.deliver_password_resets() == {'delivered': 1, 'failed': 0}
    assert len(delivered) == 2 and stale_token not in delivered
    await engine.dispose()

asyncio.run(main())
'''


def test_reset_enqueue_cannot_capture_stale_password_version(generated_service):
    service, environment = generated_service
    result = subprocess.run([sys.executable, '-c', RESET_RACE_SCENARIO], cwd=service, env=environment,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
