import os
from pathlib import Path
import subprocess
import sys

from config.plugin_models import PluginManifest
from generators.runner import run_plugin

SCENARIO = r'''
import asyncio
import grpc
from generated.protos.plugins import index_pb2 as pb
from generated.protos.plugins import index_pb2_grpc as rpc
from generated.sidecar_client import SidecarAgentClient

class Agent(rpc.PluginAgentServiceServicer):
    async def Transcribe(self, requests, context):
        metadata = dict(context.invocation_metadata())
        assert metadata['x-execution-id'] == 'execution-1'
        assert metadata['x-node-id'] == 'node-1'
        frames = [item async for item in requests]
        assert frames[0].WhichOneof('data') == 'metadata'
        config = frames[0].metadata
        if config.model == 'denied':
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Model not permitted')
        if config.model == 'slow': await asyncio.Event().wait()
        assert config.model == 'small-stt' and config.language == 'ru'
        assert all(frame.WhichOneof('data') == 'audio' and len(frame.audio) <= 65536 for frame in frames[1:])
        assert b''.join(frame.audio for frame in frames[1:]) == b'a' * 150000
        return pb.TranscriptionResponse(text='Actual recognized text', language='ru')

    async def ReadFile(self, request, context):
        assert dict(context.invocation_metadata())['x-execution-id'] == 'execution-1'
        assert request.chunk_size_bytes == 4
        if request.file_id == 'denied':
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'File not permitted')
        if request.file_id == 'slow': await asyncio.Event().wait()
        yield pb.DataChunk(sequence_number=1 if request.file_id == 'badorder' else 0,
                           payload=b'large' if request.file_id == 'oversize' else b'abcd')
        if request.file_id != 'truncated':
            yield pb.DataChunk(sequence_number=1, payload=b'ef', is_last=True)
        if request.file_id == 'aftereof':
            yield pb.DataChunk(sequence_number=2)

async def error(awaitable, expected, code=None):
    try: await awaitable
    except expected as exc:
        if code is not None: assert exc.code() == code
    else: raise AssertionError('Expected failure')

async def read(client, identifier):
    return [chunk async for chunk in client.read_file(identifier,4)]

async def main():
    server = grpc.aio.server()
    rpc.add_PluginAgentServiceServicer_to_server(Agent(),server)
    port = server.add_insecure_port('127.0.0.1:0')
    await server.start()
    try:
        async with SidecarAgentClient(f'127.0.0.1:{port}',timeout=0.2,
                execution_id='execution-1',node_id='node-1') as client:
            assert await client.transcribe(b'a'*150000,model='small-stt',language='ru') == 'Actual recognized text'
            await error(client.transcribe(b'a',model='denied'),grpc.aio.AioRpcError,grpc.StatusCode.PERMISSION_DENIED)
            await error(client.transcribe(b'a',model='slow'),grpc.aio.AioRpcError,grpc.StatusCode.DEADLINE_EXCEEDED)
            for audio in (b'',b'x'*(25*1024*1024+1)):
                await error(client.transcribe(audio,model='small-stt'),ValueError)
            assert await read(client,'file-1') == [b'abcd',b'ef']
            for identifier in ('badorder','oversize','truncated','aftereof'):
                await error(read(client,identifier),RuntimeError)
            await error(read(client,'denied'),grpc.aio.AioRpcError,grpc.StatusCode.PERMISSION_DENIED)
            await error(read(client,'slow'),grpc.aio.AioRpcError,grpc.StatusCode.DEADLINE_EXCEEDED)
            await error(read(client,'../file'),ValueError)
    finally: await server.stop(0)
asyncio.run(main())
'''


def test_media_agent_contract_real_rpc(tmp_path: Path):
    run_plugin(PluginManifest.model_validate({'plugin': {'name': 'media_rpc'}}),tmp_path/'generated')
    result = subprocess.run([sys.executable,'-c',SCENARIO],cwd=tmp_path,
                            env=dict(os.environ,PYTHONPATH=str(tmp_path)),
                            capture_output=True,text=True,timeout=30)
    assert result.returncode == 0,result.stdout+result.stderr
