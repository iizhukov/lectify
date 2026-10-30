import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from config.models import ServiceManifest
from templates import env


def test_ticket_auth_uses_dependency_manifest_port(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import generators.services.ticket_auth as module
    monkeypatch.setattr(module,'get_service_path',lambda name:tmp_path/name)
    monkeypatch.setattr(module,'get_service_manifest',lambda path:SimpleNamespace(
        service=SimpleNamespace(grpc=SimpleNamespace(port=12345))))
    manifest = ServiceManifest.model_validate({'service':{'name':'source',
        'ticket_auth':{'enabled':True,'tas_service':'custom_tas'}}})
    module.TicketAuthGenerator(manifest,tmp_path/'generated',docker=True).generate()
    source = (tmp_path/'generated/ticket_auth/client.py').read_text()
    assert 'custom_tas:12345' in source and 'clients.custom_tas.index_pb2' in source


def test_custom_ticket_dependency_generates_importable_clients(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import generators.services.grpc_client as grpc_module
    import generators.services.ticket_auth as ticket_module
    dependency = tmp_path/'custom_tas'
    dependency.mkdir()
    proto = dependency/'index.proto'
    proto.write_text('syntax="proto3"; package custom.ticket; message Request {} message Reply {} '
        'service TicketService { rpc IssueTicket(Request) returns (Reply); }')
    config = SimpleNamespace(service=SimpleNamespace(grpc=SimpleNamespace(port=12345)))
    for module in (grpc_module,ticket_module):
        monkeypatch.setattr(module,'get_service_path',lambda name:dependency)
        monkeypatch.setattr(module,'get_service_manifest',lambda path:config)
    monkeypatch.setattr(grpc_module,'get_service_proto',lambda path:proto)
    manifest = ServiceManifest.model_validate({'service':{'name':'source',
        'ticket_auth':{'enabled':True,'tas_service':'custom_tas'}}})
    output = tmp_path/'generated'
    grpc_module.GrpcClientGenerator(manifest,output).generate()
    ticket_module.TicketAuthGenerator(manifest,output).generate()
    assert (output/'protos/clients/custom_tas/index_pb2.py').exists()
    assert not (output/'protos/clients/infra_tas').exists()
    (output/'settings.py').write_text('from types import SimpleNamespace\ndef get_settings(): return SimpleNamespace(service_name="source")\n')
    (output/'logger.py').write_text('import logging\ndef get_logger(name): return logging.getLogger(name)\n')
    result = subprocess.run([sys.executable,'-c',
        'import asyncio;from generated.ticket_auth.client import TicketAuthClient\n'
        'async def main():\n client=TicketAuthClient();assert await client._get_tas_stub() is not None;await client.close()\n'
        'asyncio.run(main())'],cwd=tmp_path,env=dict(os.environ,PYTHONPATH=str(tmp_path)),
        capture_output=True,text=True,timeout=10)
    assert result.returncode == 0,result.stdout+result.stderr


SCENARIO = r'''
import asyncio, os
from pathlib import Path
import grpc
from generated.transport import TLSConfig, bind_server
from generated.grpc_clients import GrpcClients

async def main():
    for key in ('LECTIFY_GRPC_CLIENT_TLS_CERT_FILE','LECTIFY_GRPC_CLIENT_TLS_KEY_FILE','LECTIFY_GRPC_CLIENT_TLS_CA_FILE'):
        os.environ.pop(key,None)
    async def ping(request, context): return b'pong'
    server = grpc.aio.server()
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('tls.Test', {
        'Ping':grpc.unary_unary_rpc_method_handler(ping)}),))
    try:
        bind_server(server,'0.0.0.0:0')
    except ValueError: pass
    else: raise AssertionError('Remote plaintext listener accepted')
    clients = GrpcClients()
    try:
        clients.channel('unsafe',addr='worker.example:5000')
    except ValueError: pass
    else: raise AssertionError('Remote plaintext client accepted')
    tls = TLSConfig.from_files('certs/server.crt','certs/server.key','certs/ca.crt')
    from generated.transport import validate_endpoint
    validate_endpoint('api_auth:10020',secure=True)
    try: validate_endpoint('api_auth:10020')
    except ValueError: pass
    else: raise AssertionError('Docker DNS enabled plaintext fallback')
    port = bind_server(server,'127.0.0.1:0',tls)
    await server.start()
    for suffix, filename in [('CERT_FILE','client.crt'),('KEY_FILE','client.key'),('CA_FILE','ca.crt')]:
        os.environ['LECTIFY_GRPC_CLIENT_TLS_'+suffix] = str(Path('certs')/filename)
    try:
        channel = clients.channel('valid',addr=f'localhost:{port}')
        assert await channel.unary_unary('/tls.Test/Ping')(b'ping',timeout=3) == b'pong'
        wrong_name = clients.channel('wrong-name',addr=f'127.0.0.1:{port}')
        try: await wrong_name.unary_unary('/tls.Test/Ping')(b'ping',timeout=1)
        except grpc.aio.AioRpcError: pass
        else: raise AssertionError('Hostname verification bypassed')
        no_identity = grpc.aio.secure_channel(f'localhost:{port}',grpc.ssl_channel_credentials(
            root_certificates=Path('certs/ca.crt').read_bytes()))
        try:
            try: await no_identity.unary_unary('/tls.Test/Ping')(b'ping',timeout=1)
            except grpc.aio.AioRpcError: pass
            else: raise AssertionError('Client certificate was not required')
        finally: await no_identity.close()
    finally:
        await clients.close_all()
        await server.stop(0)
    from generated.grpc_server import grpc_server as bootstrap
    captured, ready = [], asyncio.Event()
    original_bind = bootstrap.bind_server
    def capture(server, address, config):
        port = original_bind(server,address,config)
        captured.append(port)
        ready.set()
        return port
    bootstrap.bind_server = capture
    for suffix, filename in [('CERT_FILE','server.crt'),('KEY_FILE','server.key'),('CA_FILE','ca.crt')]:
        os.environ['LECTIFY_GRPC_SERVER_TLS_'+suffix] = str(Path('certs')/filename)
    os.environ['LECTIFY_GRPC_LISTEN_ADDRESS'] = '127.0.0.1:0'
    def register(server):
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('tls.Test', {
            'Ping':grpc.unary_unary_rpc_method_handler(ping)}),))
    running = asyncio.create_task(bootstrap.serve(register,port=0,interceptors=[]))
    second = GrpcClients()
    try:
        await asyncio.wait_for(ready.wait(),3)
        channel = second.channel('bootstrap',addr=f'localhost:{captured[0]}')
        assert await channel.unary_unary('/tls.Test/Ping')(b'ping',timeout=3) == b'pong'
        running.cancel()
        try: await running
        except asyncio.CancelledError: pass
        try: await channel.unary_unary('/tls.Test/Ping')(b'ping',timeout=0.2)
        except grpc.aio.AioRpcError: pass
        else: raise AssertionError('Cancelled server retained its listener')
    finally:
        if not running.done():
            running.cancel()
        await asyncio.gather(running,return_exceptions=True)
        await second.close_all()
    real_factory = bootstrap.grpc.aio.server
    starting, stopping, release_stop = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class DelayedServer:
        def __init__(self,*args,**kwargs): self.real = real_factory(*args,**kwargs)
        def __getattr__(self,name): return getattr(self.real,name)
        async def start(self):
            starting.set()
            await asyncio.Event().wait()
        async def stop(self,grace):
            stopping.set()
            await release_stop.wait()
            await self.real.stop(grace)
    bootstrap.grpc.aio.server = DelayedServer
    early = asyncio.create_task(bootstrap.serve(register,port=0))
    try:
        await asyncio.wait_for(starting.wait(),3)
        early.cancel()
        await asyncio.wait_for(stopping.wait(),3)
        early.cancel()
        await asyncio.sleep(0)
        assert not early.done()
        release_stop.set()
        try: await early
        except asyncio.CancelledError: pass
        else: raise AssertionError('Cancellation was lost')
    finally:
        release_stop.set()
        if not early.done(): early.cancel()
        await asyncio.gather(early,return_exceptions=True)
        bootstrap.grpc.aio.server = real_factory
asyncio.run(main())
'''


def test_generated_service_mtls_clients_and_listener(tmp_path):
    if not shutil.which('openssl'):
        pytest.skip('OpenSSL required for temporary test certificates')
    certs = tmp_path/'certs'
    certs.mkdir()
    def openssl(*args):
        subprocess.run(['openssl',*args],cwd=certs,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    openssl('req','-x509','-nodes','-newkey','rsa:2048','-keyout','ca.key','-out','ca.crt',
        '-days','1','-subj','/CN=Test CA')
    for name in ('server','client'):
        openssl('req','-nodes','-newkey','rsa:2048','-keyout',name+'.key','-out',name+'.csr','-subj','/CN=localhost')
        (certs/'extensions.cnf').write_text('subjectAltName=DNS:localhost\nextendedKeyUsage='+
            ('serverAuth' if name=='server' else 'clientAuth')+'\n')
        openssl('x509','-req','-in',name+'.csr','-CA','ca.crt','-CAkey','ca.key','-CAcreateserial',
            '-out',name+'.crt','-days','1','-extfile','extensions.cnf')
    generated = tmp_path/'generated'
    generated.mkdir()
    (generated/'__init__.py').touch()
    (generated/'transport.py').write_text(env.get_template('plugins/transport.py.j2').render())
    manifest = ServiceManifest.model_validate({'service':{'name':'tls_test','grpc_transport':{'enabled':True}}})
    (generated/'grpc_clients.py').write_text(env.get_template('services/grpc/client/grpc_clients.py.j2').render(
        manifest=manifest,service=manifest.service,client_services=[]))
    server = generated/'grpc_server'
    server.mkdir()
    (server/'__init__.py').touch()
    (server/'grpc_app.py').write_text('METHOD_NAMES = []\n')
    (server/'grpc_server.py').write_text(env.get_template('services/grpc/server/grpc_server.py.j2').render(
        manifest=manifest,service=manifest.service))
    (generated/'settings.py').write_text('from types import SimpleNamespace\ndef get_settings(): return SimpleNamespace(grpc=SimpleNamespace(port=0))\n')
    (generated/'logger.py').write_text('from types import SimpleNamespace\ndef get_logger(name): return SimpleNamespace(info=lambda *a, **kw:None)\n')
    result = subprocess.run([sys.executable,'-c',SCENARIO],cwd=tmp_path,
        env=dict(os.environ,PYTHONPATH=str(tmp_path)),capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr
