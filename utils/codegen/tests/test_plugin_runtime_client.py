from types import ModuleType, SimpleNamespace
import sys

import pytest

from templates import env


def test_runtime_client_generation_is_independent_of_agent_server(tmp_path):
    from config.models import ServiceManifest
    from generators.services.plugin_agent import PluginAgentGenerator
    manifest = ServiceManifest.model_validate({'service':{'name':'worker',
        'plugin_runtime_client':{'enabled':True}}})
    output = tmp_path / 'generated'
    PluginAgentGenerator(manifest, output).generate()
    assert (output / 'plugin_runtime_client.py').is_file()
    assert (output / 'docker_sandbox.py').is_file()
    assert (output / 'protos/plugins/index_pb2_grpc.py').is_file()
    assert not (output / 'plugin_agent/server.py').exists()


@pytest.fixture
def client_factory(monkeypatch):
    calls = []
    class Call:
        def __init__(self, frames):
            self.frames = frames
            self.cancelled = False
        def __aiter__(self):
            async def iterate():
                for frame in self.frames:
                    yield frame
            return iterate()
        def cancel(self):
            self.cancelled = True
    class Channel:
        closed = False
        async def close(self):
            self.closed = True
    channel = Channel()
    class Stub:
        frames = []
        def ProcessStream(self, inputs, **kwargs):
            call = Call(self.frames)
            calls.append((call, kwargs))
            return call
    stub = Stub()
    for name in ('generated', 'generated.protos', 'generated.protos.plugins', 'generated.transport'):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules['generated.protos.plugins'].index_pb2_grpc = SimpleNamespace(PluginRuntimeServiceStub=lambda _:stub)
    sys.modules['generated.transport'].create_channel = lambda *args:channel
    namespace = {}
    exec(compile(env.get_template('services/plugin_runtime_client.py.j2').render(), '<runtime client>', 'exec'), namespace)
    return namespace['PluginRuntimeClient'], stub, calls, channel


def frame(sequence=0, last=True, name='output', payload=b'data'):
    return SimpleNamespace(stream_name=name, sequence_number=sequence, is_last=last, payload=payload)


@pytest.mark.asyncio
async def test_runtime_client_scopes_stream_and_closes_resources(client_factory):
    Client, stub, calls, channel = client_factory
    stub.frames = [frame()]
    async with Client('127.0.0.1:1', 'execution', 'node', 'a'*48) as client:
        result = [item async for item in client.process(None, ['output'])]
    assert len(result) == 1
    call, options = calls[0]
    assert options['wait_for_ready'] is True and options['timeout'] == 300
    assert dict(options['metadata']) == {'authorization':'Bearer '+'a'*48,
        'x-execution-id':'execution','x-node-id':'node'}
    assert call.cancelled and channel.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('frames', [[], [frame(last=False)], [frame(sequence=1)],
    [frame(name='unexpected')], [frame(),frame(sequence=1)], [frame(payload=b'x'*1048577)]])
async def test_runtime_client_rejects_invalid_or_truncated_output(client_factory, frames):
    Client, stub, calls, channel = client_factory
    stub.frames = frames
    async with Client('127.0.0.1:1', 'execution', 'node', 'a'*48) as client:
        with pytest.raises(RuntimeError):
            async for _ in client.process(None, ['output']):
                pass
    assert calls[0][0].cancelled and channel.closed
