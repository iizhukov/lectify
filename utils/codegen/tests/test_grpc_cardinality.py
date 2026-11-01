import os
import subprocess
import sys
from config.models import ServiceManifest
from templates import env


def test_generated_client_intercepts_all_four_rpc_cardinalities(tmp_path):
    manifest = ServiceManifest.model_validate({'service':{'name':'client'}})
    source = env.get_template('services/grpc/client/grpc_clients.py.j2').render(
        manifest=manifest,service=manifest.service,client_services=[])
    (tmp_path/'client.py').write_text(source)
    script = '''
import asyncio
import grpc
from client import _split_interceptors
seen = []
class Spy(grpc.aio.UnaryUnaryClientInterceptor,grpc.aio.UnaryStreamClientInterceptor,
          grpc.aio.StreamUnaryClientInterceptor,grpc.aio.StreamStreamClientInterceptor):
    async def invoke(self,continuation,details,request):
        seen.append(details.method)
        updated = grpc.aio.ClientCallDetails(details.method,details.timeout,
            [('x-ticket','verified')],details.credentials,details.wait_for_ready)
        return await continuation(updated,request)
    intercept_unary_unary=invoke
    intercept_unary_stream=invoke
    intercept_stream_unary=invoke
    intercept_stream_stream=invoke
def verify(context): assert dict(context.invocation_metadata())['x-ticket']=='verified'
async def uu(request,context): verify(context); return request
async def us(request,context): verify(context); yield request
async def su(request,context): verify(context); return b''.join([item async for item in request])
async def ss(request,context):
    verify(context)
    async for item in request: yield item
async def items(): yield b'data'
async def main():
    server=grpc.aio.server()
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('test',{
        'uu':grpc.unary_unary_rpc_method_handler(uu), 'us':grpc.unary_stream_rpc_method_handler(us),
        'su':grpc.stream_unary_rpc_method_handler(su),'ss':grpc.stream_stream_rpc_method_handler(ss)}),))
    port=server.add_insecure_port('127.0.0.1:0')
    await server.start()
    try:
        async with grpc.aio.insecure_channel('127.0.0.1:'+str(port),interceptors=_split_interceptors([Spy()])) as channel:
            assert await channel.unary_unary('/test/uu')(b'data')==b'data'
            assert [item async for item in channel.unary_stream('/test/us')(b'data')]==[b'data']
            assert await channel.stream_unary('/test/su')(items())==b'data'
            assert [item async for item in channel.stream_stream('/test/ss')(items())]==[b'data']
        assert len(seen)==4
    finally: await server.stop(0)
asyncio.run(main())
'''
    result = subprocess.run([sys.executable,'-c',script],cwd=tmp_path,
        env=dict(os.environ,PYTHONPATH=str(tmp_path)),text=True,capture_output=True,timeout=15)
    assert result.returncode == 0,result.stdout+result.stderr
