import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

root = Path(os.environ['LECTIFY_ROOT'])
source = Path(os.environ['PROVIDER_SOURCE'])
workspace = Path(sys.argv[1])
sys.path.insert(0, str(root / 'utils/codegen/src'))
from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.settings import SettingsGenerator
from generators.services.logger import LoggerGenerator
from generators.services.http import HttpGenerator
from generators.services.grpc_server import GrpcServerGenerator
import generators.services.grpc_server as grpc_generator
import yaml
manifest = ServiceManifest.model_validate(yaml.safe_load((source / 'service.yaml').read_text()))
manifest.service.ticket_auth.enabled = False
base.get_settings = lambda: SimpleNamespace(POSTGRES_PORT=5432)
base.get_context_manager = lambda: SimpleNamespace(get_service_context=lambda name: ServiceContext())
grpc_generator.get_service_proto = lambda path: root / 'proto/plugins/provider/index.proto'
for generator in (SettingsGenerator, LoggerGenerator, HttpGenerator, GrpcServerGenerator):
    generator(manifest, workspace / 'generated').generate()
shutil.copytree(source / 'src', workspace / 'src')
shutil.copy(source / 'service.yaml', workspace / 'service.yaml')
sys.path.insert(0, str(workspace))
import grpc
from generated.protos.server import index_pb2 as pb
from generated.protos.server import index_pb2_grpc as rpc
from generated.http.client import get_http_client, close_http_client
from generated.settings import get_settings
from src.service import ProviderServiceImpl
from src.adapter import PolzaAdapter, ProviderFailure
from src.policy import ProviderPolicy

requests, connections, active = [], set(), set()
connection_counter = 0
mode = 'success'
release, started = asyncio.Event(), asyncio.Event()


async def http_fixture(reader, writer):
    global connection_counter
    connection_counter += 1
    connection_id = connection_counter
    task = asyncio.current_task()
    active.add(task)
    try:
        while True:
            try:
                header = await reader.readuntil(b'\r\n\r\n')
            except (asyncio.IncompleteReadError, ConnectionResetError):
                return
            lines = header.decode().split('\r\n')
            _, path, _ = lines[0].split(' ')
            headers = {key.lower(): value for key, value in (line.split(': ', 1) for line in lines[1:] if ': ' in line)}
            assert headers['authorization'] == 'Bearer test-only-provider-token'
            assert headers['accept-encoding'] == 'identity'
            if 'content-length' in headers:
                body = await reader.readexactly(int(headers['content-length']))
            else:
                pieces = []
                while True:
                    size = int((await reader.readline()).strip(), 16)
                    if not size:
                        assert await reader.readline() == b'\r\n'
                        break
                    pieces.append(await reader.readexactly(size))
                    assert await reader.readexactly(2) == b'\r\n'
                body = b''.join(pieces)
            payload = json.loads(body)
            requests.append((path, payload))
            connections.add(connection_id)
            if mode in ('quota', 'redirect'):
                status = b'429 Too Many Requests' if mode == 'quota' else b'302 Found'
                writer.write(b'HTTP/1.1 ' + status + b'\r\nLocation: http://127.0.0.1:1/steal\r\nContent-Length: 0\r\n\r\n')
                await writer.drain()
                return
            if path.endswith('/chat/completions'):
                assert payload['model'] == 'chat-test' and payload['stream'] is True
                assert payload['max_tokens'] == 32
                if mode == 'slow':
                    await asyncio.sleep(0.3)
                if mode == 'cancel':
                    started.set()
                    await release.wait()
                chunks = [
                    'data: ' + json.dumps({'choices': [{'delta': {'content': 'Привет '}, 'finish_reason': None}]}),
                    'data: ' + json.dumps({'choices': [{'delta': {'content': 'мир'}, 'finish_reason': None}]}),
                    'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'length' if mode == 'length' else 'stop'}]}),
                    'data: ' + json.dumps({'choices': [], 'usage': {'total_tokens': 12}}),
                ]
                if mode != 'truncated':
                    chunks.append('data: [DONE]')
                if mode == 'malformed':
                    chunks = ['data: {not-json}', 'data: [DONE]']
                if mode == 'done-only':
                    chunks = ['data: [DONE]']
                if mode == 'oversized':
                    chunks = ['data: ' + 'x' * 70000]
                content = ('\n\n'.join(chunks) + '\n\n').encode()
                mime = b'text/event-stream'
            else:
                assert path.endswith('/audio/transcriptions') and payload['model'] == 'audio-test'
                prefix, audio = payload['file'].split(',', 1)
                assert prefix == 'data:audio/wav;base64' and base64.b64decode(audio) == b'abc' * 30000
                content = json.dumps({'text': 'Recognized lecture', 'language': 'ru', 'duration': 4.5}).encode()
                mime = b'application/json'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: ' + mime + b'\r\nContent-Length: ' + str(len(content)).encode() + b'\r\n\r\n')
            for offset in range(0, len(content), 3):
                writer.write(content[offset:offset+3])
                await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        active.discard(task)
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def expect_error(call, status):
    try:
        if hasattr(call, '__aiter__'):
            async for _ in call:
                pass
        else:
            await call
    except grpc.aio.AioRpcError as error:
        assert error.code() == status, error
        assert 'secret' not in error.details() and 'test-only-provider-token' not in error.details()
    else:
        raise AssertionError(f'Expected {status}')


def request(**overrides):
    data = dict(model='chat-test', messages=[pb.LLMMessage(role='user', content='lecture')],
        temperature=0.2, max_tokens=32, purpose='transform', owner_id='alice', execution_id='execution', node_id='node')
    data.update(overrides)
    return pb.LLMRequest(**data)


async def main():
    global mode
    fixture = await asyncio.start_server(http_fixture, '127.0.0.1', 0)
    port = fixture.sockets[0].getsockname()[1]
    policy = ProviderPolicy(allowed_chat_models=['chat-test'], allowed_audio_models=['audio-test'],
        allowed_purposes=['transform', 'stt'], default_chat_model='chat-test', default_audio_model='audio-test',
        max_tokens=32, timeout_seconds=0.15, max_concurrent=1)
    client = get_http_client()
    assert get_http_client() is client
    assert 'bearer_token' not in repr(get_settings().http)
    assert get_settings().extensions['provider']['max_tokens'] == 2048
    adapter = PolzaAdapter(client, 'test-only-provider-token', test_endpoint=f'http://127.0.0.1:{port}/api/v1')
    for bad_token in ('has space', 'private-token\x00', 'private-token\x7f'):
        try:
            PolzaAdapter(client, bad_token)
        except ProviderFailure as error:
            assert error.kind == 'configuration' and bad_token not in str(error)
        else:
            raise AssertionError('Invalid header token was accepted')
    class ClosingBackend:
        closed = False
        async def chat(self, payload, limits):
            try:
                yield 'first delta', False, '', 0
                await asyncio.Event().wait()
            finally:
                self.closed = True
    closing_backend = ClosingBackend()
    outer = ProviderServiceImpl(closing_backend, policy).CallLLM(request(), None)
    assert (await anext(outer)).delta_content == 'first delta'
    await outer.aclose()
    assert closing_backend.closed, 'HTTP/backend cleanup must complete before outer aclose returns'
    service = ProviderServiceImpl(adapter, policy)
    server = grpc.aio.server()
    rpc.add_ProviderServiceServicer_to_server(service, server)
    port = server.add_insecure_port('127.0.0.1:0')
    await server.start()
    channel = grpc.aio.insecure_channel(f'127.0.0.1:{port}')
    stub = rpc.ProviderServiceStub(channel)
    try:
        frames = [frame async for frame in stub.CallLLM(request())]
        assert ''.join(frame.delta_content for frame in frames) == 'Привет мир'
        assert frames[-1].is_finished and frames[-1].finish_reason == 'stop' and frames[-1].tokens_used == 12
        for payload, status in ((request(model='expensive-unlisted'), grpc.StatusCode.PERMISSION_DENIED),
                (request(purpose='unsafe'), grpc.StatusCode.PERMISSION_DENIED),
                (request(max_tokens=33), grpc.StatusCode.INVALID_ARGUMENT),
                (request(owner_id=''), grpc.StatusCode.INVALID_ARGUMENT),
                (request(extra_params={'base_url': 'http://attacker'}), grpc.StatusCode.INVALID_ARGUMENT)):
            await expect_error(stub.CallLLM(payload), status)
        assert len(requests) == 1
        service.policy = ProviderPolicy()
        await expect_error(stub.CallLLM(request()), grpc.StatusCode.PERMISSION_DENIED)
        assert len(requests) == 1
        service.policy = policy
        for scenario, status in (('truncated', grpc.StatusCode.DATA_LOSS),
                ('length', grpc.StatusCode.RESOURCE_EXHAUSTED), ('quota', grpc.StatusCode.RESOURCE_EXHAUSTED),
                ('redirect', grpc.StatusCode.UNAVAILABLE), ('slow', grpc.StatusCode.DEADLINE_EXCEEDED),
                ('malformed', grpc.StatusCode.DATA_LOSS), ('done-only', grpc.StatusCode.DATA_LOSS),
                ('oversized', grpc.StatusCode.RESOURCE_EXHAUSTED)):
            mode = scenario
            await expect_error(stub.CallLLM(request()), status)
        mode = 'success'
        async def audio(bad_eof=False):
            payload = b'abc' * 30000
            yield pb.AudioFrame(metadata=pb.AudioMetadata(model='audio-test', language='ru',
                content_type='audio/wav', size_bytes=len(payload), owner_id='alice', execution_id='execution', node_id='node'))
            yield pb.AudioFrame(chunk=payload[:65536], sequence=1)
            yield pb.AudioFrame(chunk=payload[65536:], sequence=2, is_last=not bad_eof)
        result = await stub.Transcribe(audio())
        assert result.text == 'Recognized lecture' and result.duration == 4.5
        count = len(requests)
        await expect_error(stub.Transcribe(audio(True)), grpc.StatusCode.INVALID_ARGUMENT)
        assert len(requests) == count
        mode = 'cancel'
        call = stub.CallLLM(request())
        reading = asyncio.create_task(call.read())
        await asyncio.wait_for(started.wait(), 1)
        call.cancel()
        release.set()
        await asyncio.gather(reading, return_exceptions=True)
        mode = 'success'
        after_cancel = [frame async for frame in stub.CallLLM(request())]
        assert after_cancel[-1].is_finished
        assert len(connections) < len(requests)
    finally:
        release.set()
        await channel.close()
        await server.stop(0)
        await close_http_client()
        assert client.is_closed
        fixture.close()
        await fixture.wait_closed()
        for task in list(active):
            task.cancel()
        await asyncio.gather(*list(active), return_exceptions=True)

asyncio.run(main())
