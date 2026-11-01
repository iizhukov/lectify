"""Real TAS interception must obey the user-auth deadline and own its channels."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.grpc_client import GrpcClientGenerator
from generators.services.logger import LoggerGenerator
from generators.services.settings import SettingsGenerator
from generators.services.ticket_auth import TicketAuthGenerator
from generators.services.user_auth import UserAuthGenerator

SCENARIO = r'''
import asyncio
import os
import time
import grpc
from generated.protos.clients.api_auth import index_pb2 as auth_pb
from generated.protos.clients.api_auth import index_pb2_grpc as auth_rpc
from generated.protos.clients.infra_tas import index_pb2 as tas_pb
from generated.protos.clients.infra_tas import index_pb2_grpc as tas_rpc
from generated.user_auth.client import UserAuthClient

class TAS(tas_rpc.TicketServiceServicer):
    slow = False
    async def IssueTicket(self, request, context):
        if self.slow:
            await asyncio.Event().wait()
        return tas_pb.IssueTicketResponse(ticket='service-test-ticket')

class Auth(auth_rpc.AuthServiceServicer):
    async def Authenticate(self, request, context):
        metadata = dict(context.invocation_metadata())
        assert metadata['x-service-ticket'] == 'service-test-ticket'
        return auth_pb.AuthenticateResponse(valid=True, user_id='verified-user')

async def main():
    tas = TAS()
    tas_server, auth_server = grpc.aio.server(), grpc.aio.server()
    tas_rpc.add_TicketServiceServicer_to_server(tas, tas_server)
    auth_rpc.add_AuthServiceServicer_to_server(Auth(), auth_server)
    tas_port = tas_server.add_insecure_port('127.0.0.1:0')
    auth_port = auth_server.add_insecure_port('127.0.0.1:0')
    await tas_server.start()
    await auth_server.start()
    os.environ['TAS_PROTECTED_AUTH_ADDRESS'] = f'127.0.0.1:{auth_port}'
    original = grpc.aio.insecure_channel
    created, closed = [], []
    def channel(target, *args, **kwargs):
        role = 'tas' if target == 'localhost:10010' else 'auth'
        result = original(f'127.0.0.1:{tas_port}' if role == 'tas' else target, *args, **kwargs)
        created.append((role, id(result)))
        close = result.close
        async def tracked_close(*args, **kwargs):
            closed.append((role, id(result)))
            await close(*args, **kwargs)
        result.close = tracked_close
        return result
    grpc.aio.insecure_channel = channel
    try:
        assert (await UserAuthClient().authenticate('good')).valid
        assert sorted(created) == sorted(closed)
        tas.slow = True
        started = time.monotonic()
        try:
            await UserAuthClient().authenticate('slow-tas')
        except asyncio.TimeoutError:
            pass
        else:
            raise AssertionError('TAS wait bypassed user-auth deadline')
        assert time.monotonic() - started < 0.5
        assert sorted(created) == sorted(closed)
        assert len(created) == 4 and [role for role, _ in created].count('tas') == 2
    finally:
        grpc.aio.insecure_channel = original
        await tas_server.stop(0)
        await auth_server.stop(0)
asyncio.run(main())
'''


def test_user_auth_tas_deadline_and_channel_cleanup(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(base, 'get_settings', lambda: SimpleNamespace(POSTGRES_PORT=5432))
    monkeypatch.setattr(base, 'get_context_manager', lambda: SimpleNamespace(
        get_service_context=lambda name: ServiceContext()))
    manifest = ServiceManifest.model_validate({'service': {'name': 'tas_protected',
        'ticket_auth': {'tas_service': 'infra_tas', 'enabled': True}, 'user_auth': {'auth_service': 'api_auth', 'enabled': True, 'timeout_seconds': 0.1}}})
    (tmp_path / "service.yaml").write_text(manifest.model_dump_json())
    (tmp_path / "src").mkdir()
    (tmp_path / "src/__init__.py").touch()
    for generator in (SettingsGenerator, LoggerGenerator, GrpcClientGenerator,
                      TicketAuthGenerator, UserAuthGenerator):
        generator(manifest, tmp_path/'generated').generate()
    result = subprocess.run([sys.executable, '-c', SCENARIO], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(tmp_path)),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
