"""Exercise rendered infrastructure over real gRPC, without auth/config prerequisites."""
import os
import subprocess
import sys

import pytest

from config.models import ServiceManifest
from templates import env


@pytest.mark.parametrize('enrichment', [False, True])
def test_all_cardinalities_keep_real_parent_and_status(tmp_path, enrichment):
    manifest = ServiceManifest.model_validate({'service': {'name': 'trace_client'}})
    for filename, template in [
        ('tracing.py', 'services/observability/client.py.j2'),
        ('client.py', 'services/grpc/client/grpc_clients.py.j2'),
        ('server.py', 'services/observability/middleware.py.j2'),
        ('ticket.py', 'services/ticket_auth/interceptor.py.j2'),
        ('config_flags.py', 'services/config/interceptor.py.j2'),
    ]:
        (tmp_path / filename).write_text(env.get_template(template).render(
            manifest=manifest, service=manifest.service, client_services=[]))
    script = r'''
import asyncio, sys, types
import grpc
import structlog
from opentelemetry import trace, propagate
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode, TraceState
logger=types.ModuleType('generated.logger'); logger.get_logger=structlog.get_logger
sys.modules['generated']=types.ModuleType('generated'); sys.modules['generated.logger']=logger
# Metadata interceptors use isolated infrastructure adapters in this transport test.
settings=types.ModuleType('generated.settings')
settings.get_settings=lambda: types.SimpleNamespace(service_name='test',ticket_auth=types.SimpleNamespace(ticket_ttl=60))
sys.modules['generated.settings']=settings
class TicketClient:
    async def request_ticket(self, **kwargs): return 'test-ticket'
    async def close(self): pass
module=types.ModuleType('generated.ticket_auth.client'); module.TicketAuthClient=TicketClient
sys.modules['generated.ticket_auth']=types.ModuleType('generated.ticket_auth')
sys.modules['generated.ticket_auth.client']=module
module=types.ModuleType('generated.config.client'); module.ConfigClient=type('ConfigClient',(),{})
sys.modules['generated.config']=types.ModuleType('generated.config')
sys.modules['generated.config.client']=module
from ticket import TicketAuthClientInterceptor
from config_flags import ConfigClientInterceptor
from tracing import TracingClientInterceptor
from client import _split_interceptors
from server import TracingInterceptor
exporter=InMemorySpanExporter(); provider=TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter)); trace.set_tracer_provider(provider)
seen=[]
async def uu(request, context):
    seen.append(dict(context.invocation_metadata()))
    if request==b'fail': await context.abort(grpc.StatusCode.NOT_FOUND, 'sensitive backend error')
    return request
async def us(request, context):
    yield request
    await asyncio.sleep(.01)
    yield request
async def su(request, context): return b''.join([item async for item in request])
async def ss(request, context):
    async for item in request: yield item
async def items(): yield b'data'
async def main():
    server=grpc.aio.server(interceptors=[TracingInterceptor()])
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('test.Service',{
        'uu':grpc.unary_unary_rpc_method_handler(uu), 'us':grpc.unary_stream_rpc_method_handler(us),
        'su':grpc.stream_unary_rpc_method_handler(su),'ss':grpc.stream_stream_rpc_method_handler(ss)}),))
    port=server.add_insecure_port('127.0.0.1:0'); await server.start()
    try:
        async with grpc.aio.insecure_channel('127.0.0.1:'+str(port),
                interceptors=_split_interceptors([TracingClientInterceptor()] + ([
                    TicketAuthClientInterceptor('test','backend'), ConfigClientInterceptor('test','backend')
                ] if sys.argv[1]=='True' else []))) as channel:
            parent=propagate.extract({'traceparent':'00-'+'1'*32+'-'+'2'*16+'-01','tracestate':'vendor=value'})
            with trace.get_tracer('test').start_as_current_span('root',context=parent) as root:
                assert await channel.unary_unary('/test.Service/uu')(b'data')==b'data'
                assert [x async for x in channel.unary_stream('/test.Service/us')(b'data')]==[b'data',b'data']
                assert await channel.stream_unary('/test.Service/su')(items())==b'data'
                assert [x async for x in channel.stream_stream('/test.Service/ss')(items())]==[b'data']
                try: await channel.unary_unary('/test.Service/uu')(b'fail')
                except grpc.aio.AioRpcError: pass
                else: raise AssertionError('Expected RPC failure')
            await asyncio.sleep(.05)
        spans=exporter.get_finished_spans()
        clients=[s for s in spans if s.kind==SpanKind.CLIENT]
        servers=[s for s in spans if s.kind==SpanKind.SERVER]
        assert len(clients)==len(servers)==5, [(s.name,s.kind) for s in spans]
        assert len({s.context.trace_id for s in spans})==1
        assert all(s.parent.span_id==root.get_span_context().span_id for s in clients)
        by_id={s.context.span_id:s for s in spans}
        assert all(by_id[s.parent.span_id].kind==SpanKind.CLIENT for s in servers)
        for s in servers:
            p=by_id[s.parent.span_id]
            assert p.start_time<=s.start_time<=s.end_time<=p.end_time
        assert seen[0]['tracestate']=='vendor=value'
        if sys.argv[1]=='True':
            assert seen[0]['x-service-ticket']=='test-ticket'
            assert seen[0]['x-service-name']=='test'
        assert len(seen)==2, 'An error must never retry the backend RPC'
        assert sum(s.status.status_code==StatusCode.ERROR for s in clients)==1
        assert sum(s.status.status_code==StatusCode.ERROR for s in servers)==1
        assert not any('sensitive' in str(event.attributes) for s in spans for event in s.events)
    finally: await server.stop(0)
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, '-c', script, str(enrichment)], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path)), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
