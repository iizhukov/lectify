import asyncio
from pathlib import Path
from types import SimpleNamespace

import grpc
import httpx
import pytest
import yaml
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from generated.grpc_client.grpc_clients import _split_interceptors
from generated.grpc_client.rpc_catalog import get_rpc_catalog
from generated.observability.client import TracingClientInterceptor
from generated.observability.middleware import TracingInterceptor
from generated.protos.clients.api_file import index_pb2 as files
from generated.protos.clients.api_auth import index_pb2 as auth_pb
from generated.protos.clients.infra_tas import index_pb2 as tas_pb
from src.app import create_app
from src.graph import load_plans

ROOT = Path(__file__).resolve().parents[1] / 'graphs'
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)


class Clients:
    def __init__(self, targets):
        self.channels = {name: grpc.aio.insecure_channel(target,
            interceptors=_split_interceptors([TracingClientInterceptor()])) for name, target in targets.items()}

    def channel(self, name):
        return self.channels[name]

    async def close_all(self):
        await asyncio.gather(*(channel.close() for channel in self.channels.values()))


@pytest.fixture
async def system():
    exporter.clear()
    state = SimpleNamespace(active=0, maximum=0, seen=[], cancelled=asyncio.Event(), tickets=[], require_ticket=False)

    async def inner(request, context):
        return request

    second = grpc.aio.server(interceptors=[TracingInterceptor()])
    second.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('nested.Files', {
        'Echo': grpc.unary_unary_rpc_method_handler(inner, request_deserializer=files.FileRequest.FromString,
            response_serializer=files.FileRequest.SerializeToString)}),))
    second_port = second.add_insecure_port('127.0.0.1:0')
    await second.start()
    nested_channel = grpc.aio.insecure_channel(f'127.0.0.1:{second_port}',
        interceptors=_split_interceptors([TracingClientInterceptor()]))
    nested = nested_channel.unary_unary('/nested.Files/Echo', request_serializer=files.FileRequest.SerializeToString,
        response_deserializer=files.FileRequest.FromString)

    async def get_file(request, context):
        if state.require_ticket:
            assert dict(context.invocation_metadata())['x-service-ticket'] == 'fixture-ticket'
        state.active += 1
        state.maximum = max(state.maximum, state.active)
        state.seen.append((request.id, dict(context.invocation_metadata())))
        try:
            if request.id == 'missing':
                await context.abort(grpc.StatusCode.NOT_FOUND, 'private backend detail')
            if request.id == 'slow':
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    state.cancelled.set()
                    raise
            await asyncio.sleep(.02)
            await nested(files.FileRequest(id=request.id))
            return files.File(id=request.id, filename='name', sha256='checksum')
        finally:
            state.active -= 1

    async def issue(request, context):
        state.tickets.append((request.source_service, request.target_service))
        return tas_pb.IssueTicketResponse(ticket='fixture-ticket')

    async def authenticate(request, context):
        if state.require_ticket:
            assert dict(context.invocation_metadata())['x-service-ticket'] == 'fixture-ticket'
        return auth_pb.AuthenticateResponse(valid=request.access_token == 'test-token', user_id='user', username='test')

    server = grpc.aio.server(interceptors=[TracingInterceptor()])
    server.add_generic_rpc_handlers((
        grpc.method_handlers_generic_handler('api.file.v1.FileService', {
            'GetFile': grpc.unary_unary_rpc_method_handler(get_file,
                request_deserializer=files.FileRequest.FromString, response_serializer=files.File.SerializeToString)}),
        grpc.method_handlers_generic_handler('auth.v1.AuthService', {
            'Authenticate': grpc.unary_unary_rpc_method_handler(authenticate,
                request_deserializer=auth_pb.AuthenticateRequest.FromString,
                response_serializer=auth_pb.AuthenticateResponse.SerializeToString)}),
        grpc.method_handlers_generic_handler('tas.v1.TicketService', {
            'IssueTicket': grpc.unary_unary_rpc_method_handler(issue,
                request_deserializer=tas_pb.IssueTicketRequest.FromString,
                response_serializer=tas_pb.IssueTicketResponse.SerializeToString)})))
    port = server.add_insecure_port('127.0.0.1:0')
    await server.start()
    state.target = f'127.0.0.1:{port}'
    clients = Clients({'api_file': f'127.0.0.1:{port}', 'api_auth': f'127.0.0.1:{port}'})
    app = create_app(clients=clients, catalog=get_rpc_catalog())
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway') as http:
                yield http, state, app
    finally:
        await clients.close_all()
        await nested_channel.close()
        await server.stop(0)
        await second.stop(0)


async def post(http, route='compare', left='a', right='b'):
    return await http.post('/v1/files/' + route, json=({'file_id': left} if route == 'reload' else {'left_id': left, 'right_id': right}),
        headers={'Authorization': 'Bearer test-token'})


@pytest.mark.asyncio
async def test_parallel_and_complete_trace_tree(system):
    http, state, app = system
    response = await post(http)
    assert response.status_code == 200, response.text
    assert response.json()['right']['id'] == 'b'
    assert state.maximum == 2
    assert all(meta['x-user-authorization'] == 'Bearer test-token' for _, meta in state.seen)
    spans = exporter.get_finished_spans()
    assert len({span.context.trace_id for span in spans}) == 1
    by_id = {span.context.span_id: span for span in spans}
    roots = [span for span in spans if span.parent is None]
    assert len(roots) == 1 and roots[0].kind == SpanKind.SERVER
    assert format(roots[0].context.trace_id, '032x') == response.headers['x-trace-id']
    for span in spans:
        if span.parent:
            assert span.parent.span_id in by_id, span.name
            parent = by_id[span.parent.span_id]
            assert parent.start_time <= span.start_time <= span.end_time <= parent.end_time
        if span.kind == SpanKind.SERVER and span.parent:
            assert by_id[span.parent.span_id].kind == SpanKind.CLIENT
    assert sum(span.kind == SpanKind.CLIENT for span in spans) == 5
    required = {'gateway.auth', 'gateway.input.validate', 'gateway.graph', 'gateway.node',
        'gateway.mapping.request', 'gateway.protobuf.encode', 'gateway.mapping.response',
        'gateway.output.validate', 'gateway.output.serialize', 'gateway.http.encode'}
    assert required <= {span.name for span in spans}
    assert all('test-token' not in str(span.attributes) for span in spans)
    schema = (await http.get('/openapi.json')).json()
    operation = schema['paths']['/v1/files/compare']['post']
    assert 'requestBody' in operation and operation['security']


@pytest.mark.asyncio
async def test_sequence_and_concurrent_request_isolation(system):
    http, state, _ = system
    response = await post(http, 'reload')
    assert response.status_code == 200
    assert [item[0] for item in state.seen] == ['a', 'a']
    assert state.maximum == 1
    nodes = [s for s in exporter.get_finished_spans() if s.name == 'gateway.node']
    child = next(s for s in nodes if s.attributes['graph.node'] == 'right')
    parent = next(s for s in nodes if s.attributes['graph.node'] == 'left')
    assert child.links[0].context.span_id == parent.context.span_id
    exporter.clear()
    responses = await asyncio.gather(post(http), post(http))
    assert all(r.status_code == 200 for r in responses)
    assert len({s.context.trace_id for s in exporter.get_finished_spans()}) == 2


@pytest.mark.asyncio
async def test_errors_deadline_and_input(system):
    http, state, _ = system
    assert (await http.post('/v1/files/compare', json={})).status_code == 401
    response = await post(http, left='missing')
    assert response.status_code == 404
    assert 'private backend detail' not in response.text
    assert 'private backend detail' not in str(exporter.get_finished_spans())
    response = await post(http, left='slow')
    assert response.status_code == 504
    await asyncio.wait_for(state.cancelled.wait(), 2)
    assert (await post(http, left='')).status_code == 422
    assert (await http.post('/v1/files/compare', content=b'x' * 1048577)).status_code == 413


def test_compile_rejects_invalid_graphs(tmp_path):
    import shutil
    folder = tmp_path / 'example'
    shutil.copytree(ROOT / 'compare_files', folder)
    path = folder / 'graph.yaml'
    original = yaml.safe_load(path.read_text())
    for mutate in [
        lambda g: g['nodes']['left'].update(parents=['right']),
        lambda g: g['nodes']['left'].update(parents=['absent']),
        lambda g: g['nodes']['left']['rpc'].update(method='api.file.v1.FileService/Download'),
        lambda g: g['nodes']['left']['rpc'].update(method='api.file.v1.FileService/Absent'),
        lambda g: g['response'].update(parents=['left']),
    ]:
        import copy
        graph = copy.deepcopy(original)
        mutate(graph)
        # First mutation must create a cycle.
        if graph['nodes']['left']['parents'] == ['right']:
            graph['nodes']['right']['parents'] = ['left']
        path.write_text(yaml.safe_dump(graph))
        with pytest.raises((ValueError, KeyError)):
            load_plans(tmp_path, get_rpc_catalog())


@pytest.mark.asyncio
async def test_http_disconnect_cancels_backend(system):
    import json
    http, state, app = system
    queue = asyncio.Queue()
    body = json.dumps({'left_id': 'slow', 'right_id': 'b'}).encode()
    await queue.put({'type': 'http.request', 'body': body, 'more_body': False})
    sent = []

    async def send(message):
        sent.append(message)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': '/v1/files/compare',
        'raw_path': b'/v1/files/compare', 'query_string': b'',
        'headers': [(b'authorization', b'Bearer test-token'), (b'content-type', b'application/json')],
        'client': ('127.0.0.1', 1), 'server': ('gateway', 80)}
    task = asyncio.create_task(app(scope, queue.get, send))
    try:
        async with asyncio.timeout(2):
            while not any(name == 'slow' for name, _ in state.seen):
                await asyncio.sleep(.005)
        await queue.put({'type': 'http.disconnect'})
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(state.cancelled.wait(), 2)
        assert not sent
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_mapping_failure_does_not_export_sensitive_exception(system):
    http, _, app = system
    plan = next(p for p in app.state.plans if p.graph.id == 'compare_files')
    original = plan.mappings['left']

    def broken(ctx):
        raise RuntimeError('secret mapping payload')
    plan.mappings['left'] = broken
    try:
        response = await post(http)
        assert response.status_code == 500
        assert 'secret' not in response.text
        for span in exporter.get_finished_spans():
            assert 'secret' not in str(span.attributes)
            assert 'secret' not in str(span.events)
            assert not span.status.description
    finally:
        plan.mappings['left'] = original


@pytest.mark.asyncio
async def test_real_generated_clients_include_ticket_rpc_in_trace(system, monkeypatch):
    from generated.grpc_client.grpc_clients import GrpcClients
    http, state, _ = system
    state.require_ticket = True
    for name in ['API_FILE_ADDRESS', 'API_AUTH_ADDRESS', 'LECTIFY_TAS_ADDRESS']:
        monkeypatch.setenv(name, state.target)
    exporter.clear()
    app = create_app(clients=GrpcClients(), catalog=get_rpc_catalog())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway') as http:
            response = await post(http)
    assert response.status_code == 200, response.text
    assert set(state.tickets) == {('gateway', 'api_file'), ('gateway', 'api_auth')}
    spans = exporter.get_finished_spans()
    assert len({s.context.trace_id for s in spans}) == 1
    by_id = {s.context.span_id: s for s in spans}
    ticket_spans = [s for s in spans if s.name == 'tas.v1.TicketService/IssueTicket']
    assert len(ticket_spans) >= 4
    for span in spans:
        if span.parent:
            assert span.parent.span_id in by_id
    for span in ticket_spans:
        parent = by_id[span.parent.span_id]
        assert parent.kind == SpanKind.CLIENT


def test_real_http_entrypoint_and_graceful_shutdown():
    import json
    import os
    import signal
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    environment = dict(os.environ, GATEWAY_PORT=str(port),
        GATEWAY_OBS_OTLP_ENDPOINT='http://127.0.0.1:1', GATEWAY_OBS_METRICS_ENABLED='false')
    process = subprocess.Popen([sys.executable, 'main.py'], cwd=ROOT.parent, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 8
        while True:
            assert process.poll() is None, 'Gateway exited before readiness'
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready', timeout=.3) as response:
                    assert json.load(response) == {'status': 'ready', 'graphs': 2}
                break
            except (OSError, TimeoutError):
                assert time.monotonic() < deadline, 'Gateway readiness timed out'
                time.sleep(.1)
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/openapi.json', timeout=1) as response:
            schema = json.load(response)
        assert {'/v1/files/compare', '/v1/files/reload'} <= schema['paths'].keys()
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise AssertionError('Gateway shutdown timed out') from None
    # Uvicorn re-raises the original SIGTERM after completing application shutdown.
    assert process.returncode in (0, -signal.SIGTERM)
    assert 'Application shutdown complete' in output
