import os
from pathlib import Path
import subprocess
import sys

from config.plugin_models import PluginManifest
from generators.runner import run_plugin


SCENARIO = r'''
import asyncio
import os
import grpc
from generated.server import ServerConfig, create_server, run_server, validate_endpoint
from generated.runtime import PluginRuntimeService
from generated.protos.plugins import index_pb2 as pb
from generated.protos.plugins import index_pb2_grpc as rpc

for endpoint in ('0.0.0.0:50056', '192.168.1.2:50056', '[::]:50056', 'dns:///localhost:5', '127.0.0.1:65536', 'unix:relative'):
    try: validate_endpoint(endpoint)
    except ValueError: pass
    else: raise AssertionError(endpoint)
for endpoint in ('127.0.0.1:0', '[::1]:50056', 'unix:/tmp/plugin.sock'):
    validate_endpoint(endpoint)
for key in ('LECTIFY_RUNTIME_TOKEN', 'EXECUTION_ID', 'NODE_ID'):
    saved = os.environ.pop(key)
    try:
        try: ServerConfig.from_env()
        except ValueError as error: assert saved not in str(error)
        else: raise AssertionError('Missing assignment secret accepted')
    finally: os.environ[key] = saved
assert 'test-runtime-secret' not in repr(ServerConfig.from_env())

class Sidecar:
    def __init__(self, **kwargs):
        assert kwargs == {'execution_id': 'exec-1', 'node_id': 'node-1'}
        self.assignment = kwargs
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): pass
class Handler:
    def __init__(self, **kwargs):
        assert kwargs['context'].execution_id == 'exec-1'
        assert kwargs['context'].node_id == 'node-1'
    async def on_start(self): pass
    async def process_buffer(self, data): return {'result': data.upper()}
    async def on_finish(self): pass

async def main():
    config = ServerConfig.from_env()
    server, port = create_server(config, PluginRuntimeService(Handler, Sidecar))
    await server.start()
    # Mutation of process environment cannot change the authenticated assignment.
    os.environ['EXECUTION_ID'] = 'different-execution'
    os.environ['NODE_ID'] = 'different-node'
    try:
        create_server(config, PluginRuntimeService())
    except ValueError:
        pass
    else:
        raise AssertionError('Split assignment accepted')
    authorized = [('authorization', 'Bearer test-runtime-secret'), ('x-execution-id', 'exec-1'), ('x-node-id', 'node-1')]
    async def incoming():
        yield pb.DataChunk(stream_name='input', payload=b'hello', is_last=True)
    try:
        async with grpc.aio.insecure_channel(f'127.0.0.1:{port}') as channel:
            stub = rpc.PluginRuntimeServiceStub(channel)
            for metadata, code in [
                ([], grpc.StatusCode.UNAUTHENTICATED),
                ([('authorization', 'Bearer wrong')], grpc.StatusCode.UNAUTHENTICATED),
                ([authorized[0], ('x-execution-id', 'other'), authorized[2]], grpc.StatusCode.PERMISSION_DENIED),
                ([*authorized, authorized[0]], grpc.StatusCode.UNAUTHENTICATED),
            ]:
                try: await stub.HealthCheck(pb.HealthCheckRequest(), metadata=metadata)
                except grpc.aio.AioRpcError as error: assert error.code() == code
                else: raise AssertionError('Unauthorized health accepted')
                try: [part async for part in stub.ProcessStream(incoming(), metadata=metadata)]
                except grpc.aio.AioRpcError as error: assert error.code() == code
                else: raise AssertionError('Unauthorized execution accepted')
            assert (await stub.HealthCheck(pb.HealthCheckRequest(), metadata=authorized)).healthy
            result = [part async for part in stub.ProcessStream(incoming(), metadata=authorized)]
            assert result[0].payload == b'HELLO'
            assert result[-1].is_last
    finally: await server.stop(0)
    stopped = asyncio.Event()
    stopped.set()
    await asyncio.wait_for(run_server(config, stopped), 3)
    # Shutdown an active RPC: after grace, handler and sidecar must be cancelled.
    import generated.server as bootstrap
    entered, cleaned = asyncio.Event(), asyncio.Event()
    class BlockingHandler(Handler):
        async def process_buffer(self, data):
            entered.set()
            await asyncio.Event().wait()
    class CleanupSidecar(Sidecar):
        async def __aexit__(self, *exc): cleaned.set()
    active_server, active_port = create_server(config, PluginRuntimeService(
        BlockingHandler, CleanupSidecar, execution_id='exec-1', node_id='node-1'))
    original = bootstrap.create_server
    bootstrap.create_server = lambda config: (active_server, active_port)
    stop = asyncio.Event()
    task = asyncio.create_task(run_server(config, stop))
    try:
        async with grpc.aio.insecure_channel(f'127.0.0.1:{active_port}') as channel:
            stub = rpc.PluginRuntimeServiceStub(channel)
            call = stub.ProcessStream(incoming(), metadata=authorized)
            read = asyncio.create_task(call.read())
            await asyncio.wait_for(entered.wait(), 3)
            stop.set()
            await asyncio.wait_for(task, 8)
            await asyncio.wait_for(cleaned.wait(), 2)
            try: await read
            except grpc.aio.AioRpcError: pass
            else: raise AssertionError('Active execution unexpectedly completed')
    finally:
        bootstrap.create_server = original
        stop.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

asyncio.run(main())
'''


def test_generated_authenticated_server(tmp_path: Path):
    run_plugin(PluginManifest.model_validate({'plugin': {
        'name': 'server_test', 'inputs': [{'name': 'input', 'buffer': {'strategy': 'full'}}],
        'outputs': [{'name': 'result'}],
    }}), tmp_path / 'generated')
    source = tmp_path / 'src'
    source.mkdir()
    (source / '__init__.py').touch()
    (source / 'plugin.py').write_text('class PluginHandler: pass\n')
    result = subprocess.run([sys.executable, '-c', SCENARIO], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path), PLUGIN_PARAMETERS='{}',
                 LECTIFY_RUNTIME_TOKEN='test-runtime-secret', EXECUTION_ID='exec-1', NODE_ID='node-1',
                 LECTIFY_RUNTIME_ENDPOINT='127.0.0.1:0'),
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
