"""Exercise generated code against an actual loopback gRPC agent, without Docker."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from config.plugin_models import PluginConfig, PluginManifest
from generators.plugins.protos import ProtosGenerator
from generators.runner import run_plugin


RPC_SCENARIO = r'''
import asyncio
import grpc
from generated.protos.plugins import index_pb2 as pb
from generated.protos.plugins import index_pb2_grpc as rpc
from generated.sidecar_client import SidecarAgentClient


class Agent(rpc.PluginAgentServiceServicer):
    def __init__(self):
        self.calls = []

    def check(self, context):
        metadata = dict(context.invocation_metadata())
        assert metadata['x-execution-id'] == 'execution-1'
        assert metadata['x-node-id'] == 'node-1'
        assert metadata['authorization'] == 'Bearer test-only-token'

    async def CallLLM(self, request, context):
        self.check(context)
        self.calls.append('llm')
        if request.model == 'denied':
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'not allowed')
        if request.model == 'slow':
            await asyncio.sleep(5)
        if request.model == 'truncated':
            yield pb.LLMResponse(delta_content='partial')
            return
        assert request.messages[0].content == 'hello'
        assert request.purpose == 'transform'
        assert request.extra_params['language'] == 'ru'
        yield pb.LLMResponse(delta_content='one ')
        yield pb.LLMResponse(delta_content='two', is_finished=True)

    async def SaveArtifact(self, requests, context):
        self.check(context)
        self.calls.append('artifact')
        frames = [item async for item in requests]
        assert frames[0].WhichOneof('data') == 'metadata'
        assert all(frame.WhichOneof('data') == 'chunk' for frame in frames[1:])
        assert all(len(frame.chunk) <= 65536 for frame in frames[1:])
        data = b''.join(frame.chunk for frame in frames[1:])
        if frames[0].metadata.filename == 'reject':
            return pb.SaveArtifactResponse(success=False)
        assert data == b'x' * 150000 or data == b''
        return pb.SaveArtifactResponse(
            success=True, file_id='stored-file', minio_path='result/file', size_bytes=len(data),
        )

    async def FetchPrompt(self, request, context):
        self.check(context)
        self.calls.append('prompt')
        assert request.variables['topic'] == 'lecture'
        return pb.FetchPromptResponse(prompt_id=request.prompt_id,
            system_prompt='system', user_prompt_template='{topic}', rendered_user_prompt='lecture')

    async def ReportProgress(self, request, context):
        self.check(context)
        self.calls.append('progress')
        return pb.ReportProgressResponse(acknowledged=request.percent != 13)

    async def ReportMetrics(self, request, context):
        self.check(context)
        self.calls.append('metrics')
        assert request.gauges['latency'] == 2.5
        assert request.counters['chunks'] == 1
        return pb.ReportMetricsResponse(acknowledged=True)

    async def ReportLog(self, request, context):
        self.check(context)
        self.calls.append('log')
        assert request.level == 'INFO'
        assert request.fields['count'] == '2'
        return pb.ReportLogResponse(acknowledged=True)


async def expect_error(awaitable, error):
    try:
        await awaitable
    except error as exc:
        return exc
    raise AssertionError(f'Expected {error}')


async def collect(client, model):
    return [part async for part in client.call_llm(
        model, [{'role': 'user', 'content': 'hello'}],
        purpose='transform', extra_params={'language': 'ru'},
    )]


async def main():
    agent = Agent()
    server = grpc.aio.server()
    rpc.add_PluginAgentServiceServicer_to_server(agent, server)
    port = server.add_insecure_port('127.0.0.1:0')
    assert port
    await server.start()
    endpoint = f'127.0.0.1:{port}'
    try:
        async with SidecarAgentClient(endpoint) as client:
            assert await collect(client, 'small-model') == ['one ', 'two']
            for content in (b'x' * 150000, b''):
                result = await client.save_artifact('document', 'result.txt', 'text/plain', content)
                assert result['file_id'] == 'stored-file'
                assert result['size_bytes'] == len(content)
            await expect_error(client.save_artifact('a', 'reject', 'text/plain', b''), RuntimeError)
            prompt = await client.fetch_prompt('prompt-1', {'topic': 'lecture'})
            assert prompt['rendered_user_prompt'] == 'lecture'
            await client.report_progress(42, 'working')
            await expect_error(client.report_progress(13, 'reject'), RuntimeError)
            await expect_error(client.report_progress(101, 'invalid'), ValueError)
            await client.report_metrics({'latency': 2.5}, {'chunks': 1})
            await client.log('info', 'processed', count=2)
            denied = await expect_error(collect(client, 'denied'), grpc.aio.AioRpcError)
            assert denied.code() == grpc.StatusCode.PERMISSION_DENIED
            await expect_error(collect(client, 'truncated'), RuntimeError)
        assert client._channel is None
        assert client._stub is None
        async with SidecarAgentClient(endpoint, timeout=0.05) as client:
            error = await expect_error(collect(client, 'slow'), grpc.aio.AioRpcError)
            assert error.code() == grpc.StatusCode.DEADLINE_EXCEEDED
        assert set(agent.calls) == {'llm', 'artifact', 'prompt', 'progress', 'metrics', 'log'}
    finally:
        await server.stop(0)
    for timeout in (0, -1, float('nan'), float('inf')):
        try:
            SidecarAgentClient(timeout=timeout)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid timeout accepted')

asyncio.run(main())
'''


def test_generated_agent_rpc(tmp_path: Path):
    manifest = PluginManifest(plugin=PluginConfig(name="rpc_test"))
    run_plugin(manifest, tmp_path / "generated")
    environment = dict(os.environ)
    environment.update(
        PYTHONPATH=str(tmp_path), EXECUTION_ID="execution-1", NODE_ID="node-1",
        LECTIFY_AGENT_TOKEN="test-only-token",
    )
    result = subprocess.run(
        [sys.executable, "-c", RPC_SCENARIO], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    dockerfile = (tmp_path / "generated/Dockerfile").read_text()
    assert "COPY generated/requirements.txt" in dockerfile
    requirements = (tmp_path / "generated/requirements.txt").read_text()
    assert "protobuf>=" in requirements


def test_missing_protocol_fails_generation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LECTIFY_ROOT", str(tmp_path))
    generator = ProtosGenerator(
        PluginManifest(plugin=PluginConfig(name="missing_proto")), tmp_path / "generated",
    )
    with pytest.raises(RuntimeError, match="protocol compilation failed"):
        generator.generate()


MAIN_SCENARIO = r'''
import asyncio
import json
import os
from generated import main

events = []
phase = os.environ['FAILURE_PHASE']

class Client:
    async def __aenter__(self):
        events.append('open')
        return self

    async def __aexit__(self, *exc):
        events.append('close')

    async def report_progress(self, percent, message):
        if phase == 'progress':
            raise RuntimeError('progress')

class Handler:
    def __init__(self, context, sidecar):
        pass

    async def on_start(self):
        if phase == 'start':
            raise RuntimeError('start')
        if phase == 'cancel':
            raise asyncio.CancelledError()

    async def process_buffer(self, data):
        if phase == 'process':
            raise RuntimeError('process')

    async def on_finish(self):
        if phase == 'finish':
            raise RuntimeError('finish')

main.SidecarAgentClient = Client
main.PluginHandler = Handler
try:
    asyncio.run(main.main())
except (RuntimeError, asyncio.CancelledError, json.JSONDecodeError):
    assert phase != 'success'
else:
    assert phase == 'success'
assert events == ([] if phase == 'json' else ['open', 'close']), events
'''


@pytest.mark.parametrize("phase", ["success", "start", "process", "finish", "progress", "cancel", "json"])
def test_generated_main_closes_agent(tmp_path: Path, phase):
    run_plugin(PluginManifest(plugin=PluginConfig(name="lifecycle")), tmp_path / "generated")
    source = tmp_path / "src"
    source.mkdir()
    (source / "__init__.py").touch()
    (source / "plugin.py").write_text("class PluginHandler: pass\n")
    input_path = tmp_path / "input.bin"
    input_path.write_bytes(b"payload")
    environment = dict(os.environ)
    environment.update(
        PYTHONPATH=str(tmp_path), FAILURE_PHASE=phase, STREAM_INPUT_PIPE=str(input_path),
        PLUGIN_PARAMETERS="{" if phase == "json" else "{}",
    )
    result = subprocess.run(
        [sys.executable, "-c", MAIN_SCENARIO], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
