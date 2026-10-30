"""Real gRPC plugin smoke with independent agent/runtime process groups."""
import asyncio
import os
import json
from pathlib import Path
import signal
import sys
import tempfile

from plugin_stream import Client, Policy, Proxy, StorageBackend, create_scoped_server, create_server, rpc, pb
from generated.scoped_server import ServerConfig
from generated.transport import create_channel


class ArtifactBackend(StorageBackend):
    async def save_artifact(self, **fields):
        result = await super().save_artifact(**fields)
        Path(os.environ['LECTIFY_TEST_ARTIFACT_FILE']).write_bytes(fields['data'])
        return result


async def child(role):
    token = os.environ['LECTIFY_AGENT_TOKEN']
    if role == 'agent':
        policy = Policy(execution_id='execution', node_id='node', owner_id='owner',
            plugin_name='text_to_md', storage_enabled=True, artifact_names=frozenset({'md_file'}))
        server, _ = create_scoped_server(rpc.add_PluginAgentServiceServicer_to_server,
            Proxy(policy, ArtifactBackend()), ServerConfig(token,'execution','node','127.0.0.1:50055'))
    elif role == 'plugin':
        server, _ = create_server(ServerConfig(token,'execution','node','127.0.0.1:50056'))
    else:
        raise ValueError('Invalid child role')
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    try:
        await server.start()
        await stop.wait()
    finally:
        await server.stop(0)


async def main():
    token = 'a'*48
    with tempfile.TemporaryDirectory(prefix='lectify-process-smoke-') as directory:
        artifact = Path(directory) / 'artifact.md'
        environment = dict(os.environ, EXECUTION_ID='execution', NODE_ID='node',
            LECTIFY_AGENT_TOKEN=token, LECTIFY_AGENT_ENDPOINT='127.0.0.1:50055',
            LECTIFY_RUNTIME_TOKEN=token, LECTIFY_RUNTIME_ENDPOINT='127.0.0.1:50056',
            PLUGIN_PARAMETERS='{"title":"Integration"}', LECTIFY_TEST_ARTIFACT_FILE=str(artifact))
        async def operation():
            for endpoint in ('127.0.0.1:50055','127.0.0.1:50056'):
                channel = create_channel(endpoint)
                try:
                    await asyncio.wait_for(channel.channel_ready(), 10)
                finally:
                    await channel.close()
            async def inputs():
                yield pb.DataChunk(stream_name='text_stream',sequence_number=0,payload=b'first\n\nsecond')
                yield pb.DataChunk(stream_name='text_stream',sequence_number=1,is_last=True)
            async with Client('127.0.0.1:50056','execution','node',token) as client:
                frames = [item async for item in client.process(inputs(), ['md_stream','md_file'])]
            result = b''.join(item.payload for item in frames if item.stream_name == 'md_stream')
            assert result == b'# Integration\n\nfirst\n\nsecond\n'
            assert artifact.read_bytes() == result
        environment.update(PLUGIN_MODE='supervised', LECTIFY_AGENT_COMMAND_JSON=json.dumps(
            [sys.executable, str(Path(__file__).resolve()), 'agent']))
        plugin_root = Path(__file__).resolve().parents[2] / 'plugins/format/text_to_md'
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'generated.main',
            cwd=plugin_root, env=environment)
        try:
            await operation()
        finally:
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 12)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise
        assert process.returncode == 0
    print('Independent agent and plugin processes: real gRPC stream and artifact verified; both stopped.')


if __name__ == '__main__':
    asyncio.run(child(sys.argv[1]) if len(sys.argv) == 2 else main())
