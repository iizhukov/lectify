"""Real gRPC plugin smoke with independent agent/runtime process groups."""
import asyncio
import os
import json
from pathlib import Path
import signal
import sys
import tempfile
from contextlib import AsyncExitStack

from plugin_stream import Client, Policy, Proxy, StorageBackend, create_scoped_server, create_server, rpc, pb
from generated.scoped_server import ServerConfig
from generated.transport import create_channel
from plugin_stream import load, ROOT

Controller = load('integration_controller',
    'services/orchestrator/agent/generated/plugin_agent/controller.py').PluginController
ControlClient = load('integration_control_client',
    'services/orchestrator/orchestrator/generated/plugin_control_client.py').PluginControlClient


class ArtifactBackend(StorageBackend):
    async def save_artifact(self, **fields):
        result = await super().save_artifact(**fields)
        Path(os.environ['LECTIFY_TEST_ARTIFACT_FILE']).write_bytes(fields['data'])
        return result


async def child(role):
    token = os.environ['LECTIFY_AGENT_TOKEN']
    controller = None
    if role == 'agent':
        policy = Policy(execution_id='execution', node_id='node', owner_id='owner',
            plugin_name='text_to_md', storage_enabled=True, artifact_names=frozenset({'md_file'}))
        if os.environ.get('LECTIFY_TEST_CONTROLLED') == '1':
            environment = {key:os.environ[key] for key in (
                'LECTIFY_AGENT_TOKEN','LECTIFY_AGENT_ENDPOINT','LECTIFY_RUNTIME_TOKEN',
                'LECTIFY_RUNTIME_ENDPOINT')}
            environment['PYTHONDONTWRITEBYTECODE'] = '1'
            controller = Controller('execution','node',[sys.executable,'-m','generated.main'],
                environment,str(ROOT/'plugins/format/text_to_md'))
        def register(proxy, server):
            rpc.add_PluginAgentServiceServicer_to_server(proxy,server)
            if controller:
                rpc.add_PluginControlServiceServicer_to_server(controller,server)
        server, _ = create_scoped_server(register,
            Proxy(policy, ArtifactBackend()), ServerConfig(token,'execution','node','127.0.0.1:50055',
                control_token=os.environ.get('LECTIFY_AGENT_CONTROL_TOKEN')))
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
        if controller:
            await controller.close()
        await server.stop(0)


async def main(controlled=False):
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
        if controlled:
            environment.update(LECTIFY_TEST_CONTROLLED='1',LECTIFY_AGENT_CONTROL_TOKEN='c'*48)
        plugin_root = Path(__file__).resolve().parents[2] / 'plugins/format/text_to_md'
        command = ([sys.executable,str(Path(__file__).resolve()),'agent'] if controlled
            else [sys.executable,'-m','generated.main'])
        process = await asyncio.create_subprocess_exec(*command,
            cwd=plugin_root, env=environment)
        try:
            async with AsyncExitStack() as lifecycle:
                if controlled:
                    channel = create_channel('127.0.0.1:50055')
                    try:
                        await asyncio.wait_for(channel.channel_ready(),10)
                    finally:
                        await channel.close()
                    control = await lifecycle.enter_async_context(ControlClient(
                        '127.0.0.1:50055','execution','node','c'*48))
                    assert (await control.status()).state == 'READY'
                    await lifecycle.enter_async_context(control.running('integration-start',
                        parameters_json='{"title":"Integration"}'))
                await operation()
            if controlled:
                async with ControlClient('127.0.0.1:50055','execution','node','c'*48) as control:
                    assert (await control.status()).state == 'STOPPED'
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
    asyncio.run(main(True) if sys.argv[1:] == ['--controlled'] else
        child(sys.argv[1]) if len(sys.argv) == 2 else main())
