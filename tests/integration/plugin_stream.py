"""Real runtime-client → text_to_md runtime → scoped agent gRPC integration.

Artifact storage is an explicit in-memory test backend, not the file service.
No external providers, project credentials or Docker containers are used.
"""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import grpc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'plugins/format/text_to_md'))
from generated.protos.plugins import index_pb2 as pb, index_pb2_grpc as rpc
from generated.scoped_server import ServerConfig, create_scoped_server
from generated.server import create_server


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


Client = load('integration_runtime_client',
    'services/orchestrator/orchestrator/generated/plugin_runtime_client.py').PluginRuntimeClient
Policy = load('integration_assignment_policy',
    'services/orchestrator/agent/src/policy.py').AssignmentPolicy
Proxy = load('integration_agent_proxy',
    'services/orchestrator/agent/generated/plugin_agent/proxy.py').PluginAgentProxy


class StorageBackend:
    def __init__(self):
        self.artifacts = []
    async def save_artifact(self, **fields):
        assert (fields['owner_id'], fields['execution_id'], fields['node_id']) == ('owner','execution','node')
        self.artifacts.append(fields)
        return {'file_id':'integration-file', 'size_bytes':len(fields['data'])}
    async def report_progress(self, **fields):
        assert fields['execution_id'] == 'execution' and fields['node_id'] == 'node'


async def main():
    token = 'a'*48
    os.environ.update(EXECUTION_ID='execution', NODE_ID='node', LECTIFY_AGENT_TOKEN=token,
                      PLUGIN_PARAMETERS='{"title":"Integration"}')
    backend = StorageBackend()
    policy = Policy(execution_id='execution', node_id='node', owner_id='owner',
        plugin_name='text_to_md', storage_enabled=True, artifact_names=frozenset({'md_file'}))
    agent, agent_port = create_scoped_server(rpc.add_PluginAgentServiceServicer_to_server,
        Proxy(policy, backend), ServerConfig(token, 'execution','node','127.0.0.1:0'))
    runtime = None
    try:
        await agent.start()
        os.environ['LECTIFY_AGENT_ENDPOINT'] = f'127.0.0.1:{agent_port}'
        runtime, runtime_port = create_server(ServerConfig(token,'execution','node','127.0.0.1:0'))
        await runtime.start()
        async def inputs():
            yield pb.DataChunk(stream_name='text_stream', sequence_number=0, payload=b'first\n\nsecond')
            yield pb.DataChunk(stream_name='text_stream', sequence_number=1, is_last=True)
        async with Client(f'127.0.0.1:{runtime_port}','execution','node',token) as client:
            frames = [frame async for frame in client.process(inputs(), ['md_stream','md_file'])]
        text = b''.join(frame.payload for frame in frames if frame.stream_name == 'md_stream')
        assert text == b'# Integration\n\nfirst\n\nsecond\n', text
        assert len(backend.artifacts) == 1
        assert backend.artifacts[0]['data'] == text
        assert {frame.stream_name for frame in frames if frame.is_last} == {'md_stream','md_file'}
        for node_id, credential, expected in (
            ('other-node',token,grpc.StatusCode.PERMISSION_DENIED),
            ('node','b'*48,grpc.StatusCode.UNAUTHENTICATED),
        ):
            async with Client(f'127.0.0.1:{runtime_port}','execution',node_id,credential) as client:
                try:
                    async for _ in client.process(inputs(), ['md_stream','md_file']):
                        pass
                except grpc.aio.AioRpcError as error:
                    assert error.code() == expected
                else:
                    raise AssertionError('Invalid assignment unexpectedly executed')
        assert len(backend.artifacts) == 1
        print('Real gRPC: runtime client → text_to_md plugin → scoped agent; output, blank lines and artifact verified.')
    finally:
        if runtime is not None:
            await runtime.stop(0)
        await agent.stop(0)


if __name__ == '__main__':
    asyncio.run(main())
