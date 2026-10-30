"""Execute freshly generated user identity boundaries against real gRPC."""
import os
from pathlib import Path
import subprocess
import sys

from pydantic import ValidationError
import pytest

from config.models import ServiceManifest, UserAuthConfig
from generators.services.user_auth import UserAuthGenerator
from generators.services.grpc_client import GrpcClientGenerator
from generators.services.main import MainGenerator
from generators.services.requirements import _base_requirements
from generators.services import base
from context import ServiceContext
from types import SimpleNamespace


SCENARIO = r'''
import asyncio
import json
import os
import grpc
from generated.protos.clients.api_auth import index_pb2 as pb
from generated.protos.clients.api_auth import index_pb2_grpc as rpc
from generated.user_auth.interceptor import UserAuthServerInterceptor


class Auth(rpc.AuthServiceServicer):
    revoked = False
    calls = 0
    async def Authenticate(self, request, context):
        self.calls += 1
        if request.access_token == 'slow':
            await asyncio.sleep(2)
        if request.access_token == 'down':
            await context.abort(grpc.StatusCode.INTERNAL, 'sensitive backend information')
        if request.access_token == 'denied' or self.revoked:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'token secret')
        return pb.AuthenticateResponse(valid=request.access_token != 'invalid',
            user_id='verified-user', is_admin=False, username='alice')


async def expect_error(call, code):
    try:
        if hasattr(call, '__aiter__'):
            async for _ in call:
                pass
        else:
            await call
    except grpc.aio.AioRpcError as error:
        assert error.code() == code, error
        assert 'secret' not in error.details() and 'sensitive' not in error.details()
    else:
        raise AssertionError('Unauthorized request was allowed')


async def main():
    auth = Auth()
    backend = grpc.aio.server()
    rpc.add_AuthServiceServicer_to_server(auth, backend)
    port = backend.add_insecure_port('127.0.0.1:0')
    await backend.start()
    os.environ['PROTECTED_TEST_AUTH_ADDRESS'] = f'127.0.0.1:{port}'
    calls = []
    def principal(context):
        value = context.lectify_principal
        calls.append(value)
        return json.dumps({'user_id': value.user_id, 'admin': value.is_admin}).encode()
    async def uu(request, context):
        return principal(context)
    async def us(request, context):
        yield principal(context)
    async def su(requests, context):
        async for _ in requests:
            pass
        return principal(context)
    async def ss(requests, context):
        async for _ in requests:
            yield principal(context)
    protected = grpc.aio.server(interceptors=[UserAuthServerInterceptor()])
    protected.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('protected.Test', {
        'UU': grpc.unary_unary_rpc_method_handler(uu),
        'US': grpc.unary_stream_rpc_method_handler(us),
        'SU': grpc.stream_unary_rpc_method_handler(su),
        'SS': grpc.stream_stream_rpc_method_handler(ss),
    }),))
    port = protected.add_insecure_port('127.0.0.1:0')
    await protected.start()
    channel = grpc.aio.insecure_channel(f'127.0.0.1:{port}')
    good = (('x-user-authorization', 'Bearer good'), ('x-user-id', 'attacker'), ('x-is-admin', 'true'))
    try:
        for headers in ((), (('x-user-id', 'attacker'),),
                        (('x-user-authorization', 'Bearer '),),
                        (('x-user-authorization', 'Bearer good'), ('x-user-authorization', 'Bearer good'))):
            await expect_error(channel.unary_unary('/protected.Test/UU')(b'', metadata=headers), grpc.StatusCode.UNAUTHENTICATED)
        assert auth.calls == 0 and not calls
        assert json.loads(await channel.unary_unary('/protected.Test/UU')(b'', metadata=good)) == {
            'user_id': 'verified-user', 'admin': False}
        assert len([item async for item in channel.unary_stream('/protected.Test/US')(b'', metadata=good)]) == 1
        assert await channel.stream_unary('/protected.Test/SU')(iter([b'a']), metadata=good)
        assert len([item async for item in channel.stream_stream('/protected.Test/SS')(iter([b'a']), metadata=good)]) == 1
        for token, status in (('denied', grpc.StatusCode.UNAUTHENTICATED),
                              ('invalid', grpc.StatusCode.UNAUTHENTICATED),
                              ('slow', grpc.StatusCode.UNAVAILABLE),
                              ('down', grpc.StatusCode.UNAVAILABLE)):
            await expect_error(channel.unary_unary('/protected.Test/UU')(b'',
                metadata=(('x-user-authorization', 'Bearer ' + token),)), status)
        assert len(calls) == 4
        auth.revoked = True
        await expect_error(channel.unary_unary('/protected.Test/UU')(b'', metadata=good), grpc.StatusCode.UNAUTHENTICATED)
        assert len(calls) == 4
    finally:
        await channel.close()
        await protected.stop(0)
        await backend.stop(0)

asyncio.run(main())
'''


def test_user_auth_generated_rpc(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(base, 'get_settings', lambda: SimpleNamespace(POSTGRES_PORT=5432))
    monkeypatch.setattr(base, 'get_context_manager', lambda: SimpleNamespace(
        get_service_context=lambda name: ServiceContext()))
    manifest = ServiceManifest.model_validate({'service': {'name': 'protected_test',
        'user_auth': {'enabled': True, 'timeout_seconds': 0.05}}})
    # user_auth alone automatically adds its AuthService client.
    GrpcClientGenerator(manifest, tmp_path / 'generated').generate()
    UserAuthGenerator(manifest, tmp_path / 'generated').generate()
    main_source = MainGenerator(manifest, tmp_path / 'generated').render('services/main/main.py.j2')
    compile(main_source, 'generated_main.py', 'exec')
    assert 'run_scheduler' not in main_source
    assert 'croniter' not in '\n'.join(_base_requirements(manifest.service))
    environment = dict(os.environ, PYTHONPATH=str(tmp_path))
    result = subprocess.run([sys.executable, '-c', SCENARIO], cwd=tmp_path,
        env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf'), 31])
def test_timeout_must_be_finite_and_bounded(timeout):
    with pytest.raises(ValidationError):
        UserAuthConfig(timeout_seconds=timeout)
