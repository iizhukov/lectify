import os
from pathlib import Path
import subprocess
import sys

from config.models import ServiceManifest
from generators.services.plugin_agent import PluginAgentGenerator
from templates import env


SCENARIO = r'''
import asyncio, json, os, signal, sys
from pathlib import Path
import grpc
from generated.plugin_agent.controller import PluginController
from generated.plugin_agent.server import create_server, load_assignment
from generated.plugin_control_client import PluginControlClient
from generated.scoped_server import ServerConfig, run_scoped_server, create_scoped_server
from generated.protos.plugins import index_pb2 as pb, index_pb2_grpc as rpc

async def rejected(awaitable, code):
    try: await awaitable
    except grpc.aio.AioRpcError as error: assert error.code() == code,error.code()
    else: raise AssertionError('Unauthorized control operation accepted')

async def main():
    os.environ.pop('LECTIFY_AGENT_ASSIGNMENT_FILE',None)
    os.environ['LECTIFY_AGENT_ASSIGNMENT_JSON'] = '{"execution_id":"execution","node_id":"node"}'
    assert load_assignment() == {'execution_id':'execution','node_id':'node'}
    assert 'LECTIFY_AGENT_ASSIGNMENT_JSON' not in os.environ
    for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '[]', ' '*32769):
        os.environ['LECTIFY_AGENT_ASSIGNMENT_JSON'] = raw
        try: load_assignment()
        except ValueError: pass
        else: raise AssertionError('Invalid assignment accepted')
    os.mkfifo('assignment.fifo',0o600)
    os.environ['LECTIFY_AGENT_ASSIGNMENT_FILE'] = str(Path('assignment.fifo').resolve())
    try:
        try: load_assignment()
        except ValueError: pass
        else: raise AssertionError('FIFO assignment accepted')
    finally: os.environ.pop('LECTIFY_AGENT_ASSIGNMENT_FILE')
    os.environ['AGENT_ONLY_SECRET'] = 'not-in-child'
    captured=[]
    async def log_sink(level,message,fields): captured.append((message,fields))
    child = ('import os,time,json,sys;from pathlib import Path;'
        'print("runtime stdout "+os.environ["RUNTIME_TOKEN"],flush=True);'
        'print("runtime stderr diagnostic",file=sys.stderr,flush=True);'
        'Path("spawns").open("a").write(str(os.getpid())+"\\n");'
        'Path("child.json.tmp").write_text(json.dumps(dict(os.environ)));'
        'Path("child.json.tmp").replace("child.json");time.sleep(60)')
    controller = PluginController('execution','node',[sys.executable,'-c',child],
        {'EXECUTION_ID':'wrong','NODE_ID':'wrong','PLUGIN_MODE':'pipe','RUNTIME_TOKEN':'runtime-fixture-sensitive-value'},str(Path.cwd()),log_sink=log_sink)
    class Proxy(rpc.PluginAgentServiceServicer): assignment = ('execution','node')
    config = ServerConfig('p'*48,'execution','node','127.0.0.1:0',control_token='c'*48)
    owned = []
    server, port = create_server(config,Proxy(),controller,_controllers=owned)
    assert owned == [controller]
    await server.start()
    endpoint = f'127.0.0.1:{port}'
    try:
        async with PluginControlClient(endpoint,'execution','node','p'*48) as wrong:
            await rejected(wrong.status(),grpc.StatusCode.UNAUTHENTICATED)
        async with PluginControlClient(endpoint,'execution','other','c'*48) as wrong:
            await rejected(wrong.status(),grpc.StatusCode.PERMISSION_DENIED)
        async with PluginControlClient(endpoint,'execution','node','c'*48) as client:
            assert (await client.status()).state == 'READY'
            parameters = {'text':'','caption':'Привет','nested':{'enabled':True,'count':1,'optional':None},'EXECUTION_ID':'spoof'}
            raw = json.dumps(parameters,ensure_ascii=False,separators=(',',':'))
            parameters['text'] = 'x'*(65536-len(raw.encode()))
            raw = json.dumps(parameters,ensure_ascii=False,separators=(',',':'))
            assert len(raw.encode()) == 65536
            replies = await asyncio.gather(client.start('start-one',parameters_json=raw),
                client.start('start-one',parameters_json=raw))
            assert all(reply.state == 'RUNNING' for reply in replies)
            async with asyncio.timeout(3):
                while not Path('child.json').exists(): await asyncio.sleep(0.01)
            child_environment = json.loads(Path('child.json').read_text())
            assert child_environment['EXECUTION_ID'] == 'execution'
            assert child_environment['NODE_ID'] == 'node' and child_environment['PLUGIN_MODE'] == 'server'
            assert json.loads(child_environment['PLUGIN_PARAMETERS']) == parameters
            assert 'AGENT_ONLY_SECRET' not in child_environment
            assert Path('spawns').read_text().splitlines() == [str(controller._process.pid)]
            await rejected(client.start('different-start'),grpc.StatusCode.ALREADY_EXISTS)
            reordered = json.dumps(dict(reversed(tuple(parameters.items()))),ensure_ascii=False,separators=(',',':'))
            assert (await client.start('start-one',parameters_json=reordered)).state == 'RUNNING'
            await rejected(client.start('start-one',parameters_json='{"text":"changed"}'),grpc.StatusCode.ALREADY_EXISTS)
            assert (await client.start('start-one')).state == 'RUNNING'
            expansion = '{"v":['+','.join(['1e9']*8000)+']}'
            for bad in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e999}','[]','',raw+' ',expansion):
                await rejected(client._stub.Start(pb.ControlCommand(command_id='invalid',parameters_json=bad),
                    metadata=client._metadata,timeout=2),grpc.StatusCode.INVALID_ARGUMENT)
            for invalid in ('[]',expansion):
                try:
                    async with client.running('start-one',parameters_json=invalid): pass
                except ValueError: pass
                else: raise AssertionError('Invalid parameters accepted by client')
            async def conflict(command):
                async with client.running(command,parameters_json='{}'):
                    raise AssertionError('Conflicting Start accepted')
            for command in ('different-start','start-one'):
                await rejected(conflict(command),grpc.StatusCode.ALREADY_EXISTS)
            assert (await client.status()).state == 'RUNNING'
            try:
                async with client.running('start-one'):
                    raise RuntimeError('consumer failed')
            except RuntimeError as error: assert str(error) == 'consumer failed'
            else: raise AssertionError('Consumer error lost')
            assert (await client.status()).state == 'STOPPED'
            text=''.join(message for message,_ in captured)
            assert 'runtime stdout' in text and 'runtime stderr diagnostic' in text
            assert 'runtime-fixture-sensitive-value' not in text and '[REDACTED]' in text
            assert {fields['stream'] for _,fields in captured}=={'stdout','stderr'}
            for _ in range(2): assert (await client.stop('stop-one')).state == 'STOPPED'
            assert (await client.status()).state == 'STOPPED'
            await rejected(client.start('start-one'),grpc.StatusCode.FAILED_PRECONDITION)
            try: os.kill(controller._process.pid,0)
            except ProcessLookupError: pass
            else: raise AssertionError('Stopped runtime process was not reaped')
        channel = grpc.aio.insecure_channel(endpoint)
        try:
            await rejected(rpc.PluginAgentServiceStub(channel).ReportProgress(pb.ReportProgressRequest(percent=1),
                metadata=(('authorization','Bearer '+'c'*48),('x-execution-id','execution'),('x-node-id','node'))),
                grpc.StatusCode.UNAUTHENTICATED)
        finally: await channel.close()
    finally:
        await controller.close()
        await server.stop(0)
async def shutdown_cancellation():
    entered, release = asyncio.Event(), asyncio.Event()
    class Server:
        calls = 0
        async def start(self): pass
        async def stop(self, grace):
            self.calls += 1
            entered.set()
            await release.wait()
    server = Server()
    stop = asyncio.Event()
    stop.set()
    task = asyncio.create_task(run_scoped_server(lambda config: (server,0),stop_event=stop))
    await entered.wait()
    for _ in range(2):
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    release.set()
    try: await task
    except asyncio.CancelledError: pass
    else: raise AssertionError('Caller cancellation was lost')
    assert server.calls == 1

asyncio.run(main())
asyncio.run(shutdown_cancellation())

async def lost_start_response():
    entered, release = asyncio.Event(), asyncio.Event()
    class Client:
        stops = 0
        async def start(self, command): raise RuntimeError('response lost')
        async def stop(self, command):
            self.stops += 1
            entered.set()
            await release.wait()
    client = Client()
    async def run():
        async with PluginControlClient.running(client,'attempt'):
            raise AssertionError('Start failed')
    task = asyncio.create_task(run())
    await entered.wait()
    for _ in range(2):
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    release.set()
    try: await task
    except asyncio.CancelledError: pass
    else: raise AssertionError('Cancellation lost')
    assert client.stops == 1
asyncio.run(lost_start_response())

async def delayed_runtime_listener():
    from generated.plugin_runtime_client import PluginRuntimeClient
    class Runtime(rpc.PluginRuntimeServiceServicer):
        async def ProcessStream(self, requests, context):
            assert dict(context.invocation_metadata())['authorization'] == 'Bearer '+'r'*48
            yield pb.DataChunk(stream_name='out',sequence_number=0,is_last=True)
    server = grpc.aio.server()
    rpc.add_PluginRuntimeServiceServicer_to_server(Runtime(),server)
    port = server.add_insecure_port('127.0.0.1:0')
    async def inputs():
        if False: yield
    async def collect():
        async with PluginRuntimeClient(f'127.0.0.1:{port}','execution','node','r'*48,timeout=5) as client:
            return [frame async for frame in client.process(inputs(),['out'])]
    task = asyncio.create_task(collect())
    try:
        await asyncio.sleep(0.15)
        assert not task.done()
        await server.start()
        assert (await task)[0].is_last
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        await server.stop(0)
asyncio.run(delayed_runtime_listener())

async def legacy_agent_requires_explicit_parameter_support():
    calls = []
    class Legacy(rpc.PluginControlServiceServicer):
        assignment = ('execution','node')
        async def Status(self, request, context): return pb.ControlStatus(state='READY')
        async def Start(self, request, context):
            calls.append('start')
            return pb.ControlStatus(state='RUNNING')
        async def Stop(self, request, context):
            calls.append('stop')
            return pb.ControlStatus(state='STOPPED')
    config = ServerConfig('p'*48,'execution','node','127.0.0.1:0',control_token='c'*48)
    server,port = create_scoped_server(rpc.add_PluginControlServiceServicer_to_server,Legacy(),config)
    await server.start()
    try:
        async with PluginControlClient(f'127.0.0.1:{port}','execution','node','c'*48) as client:
            try:
                async with client.running('attempt',parameters_json='{}'): pass
            except ValueError: pass
            else: raise AssertionError('Legacy agent silently ignored parameters')
            assert not calls
            async with client.running('legacy'): pass
            assert calls == ['start','stop']
    finally: await server.stop(0)
asyncio.run(legacy_agent_requires_explicit_parameter_support())
'''


def test_generated_control_roles_and_process_lifecycle(tmp_path: Path):
    manifest = ServiceManifest.model_validate({'service':{'name':'control_agent','plugin_agent':{'enabled':True}}})
    output = tmp_path/'generated'
    PluginAgentGenerator(manifest,output).generate()
    (output/'plugin_control_client.py').write_text(env.get_template('services/plugin_control_client.py.j2').render())
    (output/'plugin_runtime_client.py').write_text(env.get_template('services/plugin_runtime_client.py.j2').render())
    result = subprocess.run([sys.executable,'-c',SCENARIO],cwd=tmp_path,
        env=dict(os.environ,PYTHONPATH=str(tmp_path)),capture_output=True,text=True,timeout=30)
    assert result.returncode == 0,result.stdout+result.stderr
