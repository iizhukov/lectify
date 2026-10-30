import os
from pathlib import Path
import subprocess
import sys

from config.plugin_models import PluginManifest
from generators.runner import run_plugin


SCENARIO = r'''
import asyncio
import grpc
from generated import runtime
from generated.protos.plugins import index_pb2 as pb
from generated.protos.plugins import index_pb2_grpc as rpc

closed = []
class Sidecar:
    def __init__(self, **kwargs): self.assignment = kwargs
    async def __aenter__(self): return self
    async def __aexit__(self, *args): closed.append(True)
class Handler:
    def __init__(self, **kwargs): self.value = b''
    async def on_start(self): pass
    async def process_buffer(self, value):
        if value == b'fail': raise RuntimeError('secret internal detail')
        if value == b'wrong': return {'undeclared': value}
        return {'result': value.upper()}
    async def on_finish(self): pass

async def main():
    server = grpc.aio.server()
    rpc.add_PluginRuntimeServiceServicer_to_server(runtime.PluginRuntimeService(
        Handler, Sidecar, max_chunk_bytes=8, max_buffer_bytes=16), server)
    port = server.add_insecure_port('127.0.0.1:0')
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f'127.0.0.1:{port}') as channel:
            stub = rpc.PluginRuntimeServiceStub(channel)
            assert (await stub.HealthCheck(pb.HealthCheckRequest())).healthy
            async def run(chunks):
                async def incoming():
                    for chunk in chunks: yield chunk
                return [item async for item in stub.ProcessStream(incoming())]
            result = await run([pb.DataChunk(stream_name='input', payload=b'hello', is_last=True)])
            assert [(x.payload, x.sequence_number, x.is_last) for x in result] == [(b'HELLO', 0, False), (b'', 1, True)]
            cases = [
                ([pb.DataChunk(stream_name='unknown')], grpc.StatusCode.INVALID_ARGUMENT),
                ([pb.DataChunk(stream_name='input', sequence_number=1)], grpc.StatusCode.INVALID_ARGUMENT),
                ([pb.DataChunk(stream_name='input', payload=b'hello')], grpc.StatusCode.INVALID_ARGUMENT),
                ([pb.DataChunk(stream_name='input', payload=b'123456789')], grpc.StatusCode.RESOURCE_EXHAUSTED),
                ([pb.DataChunk(stream_name='input', payload=b'fail', is_last=True)], grpc.StatusCode.INTERNAL),
                ([pb.DataChunk(stream_name='input', payload=b'wrong', is_last=True)], grpc.StatusCode.INVALID_ARGUMENT),
                ([pb.DataChunk(stream_name='input', sequence_number=i, payload=b'12345678') for i in range(3)], grpc.StatusCode.RESOURCE_EXHAUSTED),
                ([pb.DataChunk(stream_name='input', is_last=True), pb.DataChunk(stream_name='input', sequence_number=1)], grpc.StatusCode.INVALID_ARGUMENT),
            ]
            for chunks, expected in cases:
                try: await run(chunks)
                except grpc.aio.AioRpcError as error:
                    assert error.code() == expected, error
                    assert 'secret internal detail' not in error.details()
                else: raise AssertionError('Expected rejection')
            assert len(closed) == 9
            # Timer flush must happen even if the next input has not arrived.
            runtime.INPUTS['input']['strategy'] = 'time'
            runtime.INPUTS['input']['time_window_ms'] = 100
            received = asyncio.Event()
            async def delayed():
                yield pb.DataChunk(stream_name='input', payload=b'timer')
                await received.wait()
                yield pb.DataChunk(stream_name='input', sequence_number=1, is_last=True)
            call = stub.ProcessStream(delayed())
            first = await asyncio.wait_for(call.read(), 2)
            assert first.payload == b'TIMER'
            received.set()
            terminal = await asyncio.wait_for(call.read(), 2)
            assert terminal.is_last
            assert await call.read() is grpc.aio.EOF
            # Named inputs are dispatched without losing their identity.
            runtime.INPUTS['other'] = dict(runtime.INPUTS['input'], strategy='full')
            async def named(self, name, value):
                return {'result': name.encode() + b':' + value}
            Handler.process_input = named
            multi = await run([
                pb.DataChunk(stream_name='input', payload=b'a', is_last=True),
                pb.DataChunk(stream_name='other', payload=b'b', is_last=True),
            ])
            assert b''.join(item.payload for item in multi) == b'input:aother:b'
            assert multi[-1].is_last
            del runtime.INPUTS['other']
            del Handler.process_input
            # Source plugins produce named outputs without an input port.
            inputs = dict(runtime.INPUTS)
            runtime.INPUTS.clear()
            async def produce(self):
                yield {'result': b'first'}
                yield {'result': b'second'}
            Handler.produce = produce
            source = await run([])
            assert [frame.payload for frame in source] == [b'first', b'second', b'']
            assert [frame.sequence_number for frame in source] == [0, 1, 2]
            assert source[-1].is_last
            runtime.INPUTS.update(inputs)
            del Handler.produce
            # Cancellation while waiting for another chunk still closes sidecar.
            never = asyncio.Event()
            async def idle():
                yield pb.DataChunk(stream_name='input', payload=b'cancel')
                await never.wait()
            call = stub.ProcessStream(idle())
            assert (await asyncio.wait_for(call.read(), 2)).payload == b'CANCEL'
            before = len(closed)
            call.cancel()
            for _ in range(100):
                if len(closed) > before: break
                await asyncio.sleep(0.01)
            assert len(closed) == before + 1

    finally:
        await server.stop(0)
asyncio.run(main())
'''


def test_generated_runtime_real_rpc(tmp_path: Path):
    run_plugin(PluginManifest.model_validate({'plugin': {
        'name': 'runtime_test', 'inputs': [{'name': 'input', 'buffer': {'strategy': 'full'}}],
        'outputs': [{'name': 'result'}],
    }}), tmp_path / 'generated')
    source = tmp_path / 'src'
    source.mkdir()
    (source / '__init__.py').touch()
    (source / 'plugin.py').write_text('class PluginHandler: pass\n')
    result = subprocess.run([sys.executable, '-c', SCENARIO], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(tmp_path), PLUGIN_PARAMETERS='{}'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
