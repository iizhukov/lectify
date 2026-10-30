import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from config.plugin_models import PluginManifest
from generators.runner import run_plugin


SCENARIO = r'''
import asyncio
import os
from pathlib import Path
import grpc
from generated.server import ServerConfig, create_server
from generated.transport import TLSConfig, create_channel
from generated.sidecar_client import SidecarAgentClient
from generated.protos.plugins import index_pb2 as pb
from generated.protos.plugins import index_pb2_grpc as rpc

root = Path('certs')
ca = (root/'ca.crt').read_bytes()
client = TLSConfig.from_files(root/'client.crt', root/'client.key', root/'ca.crt')
config = ServerConfig('runtime-test-token', 'exec', 'node', '127.0.0.1:0',
                      str(root/'server.crt'), str(root/'server.key'), str(root/'ca.crt'))
ServerConfig('runtime-test-token', 'exec', 'node', '0.0.0.0:50056',
             str(root/'server.crt'), str(root/'server.key'), str(root/'ca.crt'))
for paths in [(root/'server.crt',None,None), (None, root/'server.key',root/'ca.crt')]:
    try: TLSConfig.from_files(*paths)
    except ValueError: pass
    else: raise AssertionError('Incomplete TLS accepted')
try: ServerConfig('runtime-test-token','exec','node',tls_cert_file=str(root/'server.crt'))
except ValueError: pass
else: raise AssertionError('Incomplete server TLS accepted before bind')
os.environ['LECTIFY_AGENT_TLS_CERT_FILE'] = str(root/'client.crt')
try:
    try: SidecarAgentClient('127.0.0.1:50055')
    except ValueError: pass
    else: raise AssertionError('Incomplete sidecar TLS silently downgraded')
finally: del os.environ['LECTIFY_AGENT_TLS_CERT_FILE']
try: ServerConfig('runtime-test-token','exec','node','0.0.0.0:50056')
except ValueError: pass
else: raise AssertionError('Remote insecure server accepted')
try: SidecarAgentClient('worker.example:50055')
except ValueError: pass
else: raise AssertionError('Remote insecure sidecar accepted')

class Agent(rpc.PluginAgentServiceServicer):
    async def ReportProgress(self, request, context):
        return pb.ReportProgressResponse(acknowledged=True)

async def main():
    server, port = create_server(config)
    rpc.add_PluginAgentServiceServicer_to_server(Agent(), server)
    await server.start()
    endpoint = f'127.0.0.1:{port}'
    authorized = [('authorization','Bearer runtime-test-token'),('x-execution-id','exec'),('x-node-id','node')]
    try:
        async with create_channel(endpoint, client) as channel:
            stub = rpc.PluginRuntimeServiceStub(channel)
            assert (await stub.HealthCheck(pb.HealthCheckRequest(),metadata=authorized,timeout=3)).healthy
            try: await stub.HealthCheck(pb.HealthCheckRequest(),timeout=3)
            except grpc.aio.AioRpcError as error: assert error.code() == grpc.StatusCode.UNAUTHENTICATED
            else: raise AssertionError('mTLS bypassed bearer authentication')
        async with SidecarAgentClient(endpoint,tls=client,execution_id='exec',node_id='node') as sidecar:
            await sidecar.report_progress(42,'working')
        invalid_credentials = [
            grpc.ssl_channel_credentials(root_certificates=ca),
            grpc.ssl_channel_credentials(root_certificates=(root/'rogue.crt').read_bytes(),
                private_key=(root/'client.key').read_bytes(),certificate_chain=(root/'client.crt').read_bytes()),
            grpc.ssl_channel_credentials(root_certificates=ca,
                private_key=(root/'rogue.key').read_bytes(),certificate_chain=(root/'rogue.crt').read_bytes()),
        ]
        for credentials in invalid_credentials:
            async with grpc.aio.secure_channel(endpoint, credentials) as channel:
                try:
                    await rpc.PluginRuntimeServiceStub(channel).HealthCheck(pb.HealthCheckRequest(),metadata=authorized,timeout=2)
                except grpc.aio.AioRpcError as error: assert error.code() in (grpc.StatusCode.UNAVAILABLE,grpc.StatusCode.DEADLINE_EXCEEDED)
                else: raise AssertionError('Client certificate requirement bypassed')
    finally: await server.stop(0)
asyncio.run(main())
'''


def test_generated_mtls_transport(tmp_path: Path):
    assert shutil.which('openssl'), 'openssl is required for local certificate fixtures'
    certificates = tmp_path / 'certs'
    certificates.mkdir()

    def openssl(*arguments):
        subprocess.run(['openssl', *arguments], cwd=certificates, check=True,
                       capture_output=True, timeout=30)

    for name in ('ca', 'rogue'):
        openssl('req', '-x509', '-nodes', '-newkey', 'rsa:2048', '-days', '1',
                '-keyout', name + '.key', '-out', name + '.crt', '-subj', '/CN=Test-' + name)
    for name in ('server', 'client'):
        openssl('req', '-nodes', '-newkey', 'rsa:2048', '-keyout', name + '.key',
                '-out', name + '.csr', '-subj', '/CN=localhost')
        (certificates / 'extensions.cnf').write_text(
            'subjectAltName=IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=' +
            ('serverAuth' if name == 'server' else 'clientAuth') + '\n')
        openssl('x509', '-req', '-in', name + '.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key',
                '-CAcreateserial', '-out', name + '.crt', '-days', '1', '-extfile', 'extensions.cnf')
    run_plugin(PluginManifest.model_validate({'plugin': {'name': 'mtls_test'}}), tmp_path/'generated')
    source = tmp_path/'src'
    source.mkdir()
    (source/'__init__.py').touch()
    (source/'plugin.py').write_text('class PluginHandler: pass\n')
    result = subprocess.run([sys.executable, '-c', SCENARIO], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(tmp_path), LECTIFY_AGENT_TOKEN='runtime-test-token'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
