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
from generated.plugin_agent.server import create_server
from generated.plugin_control_client import PluginControlClient
from generated.scoped_server import ServerConfig, run_scoped_server
from generated.protos.plugins import index_pb2 as pb, index_pb2_grpc as rpc

async def rejected(awaitable, code):
    try: await awaitable
    except grpc.aio.AioRpcError as error: assert error.code() == code,error.code()
    else: raise AssertionError('Unauthorized control operation accepted')

async def main():
    os.environ['AGENT_ONLY_SECRET'] = 'not-in-child'
    child = ('import os,time,json;from pathlib import Path;'
        'Path("spawns").open("a").write(str(os.getpid())+"\\n");'
        'Path("child.json").write_text(json.dumps(dict(os.environ)));time.sleep(60)')
    controller = PluginController('execution','node',[sys.executable,'-c',child],
        {'EXECUTION_ID':'wrong','NODE_ID':'wrong','PLUGIN_MODE':'pipe'},str(Path.cwd()))
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
            replies = await asyncio.gather(client.start('start-one'),client.start('start-one'))
            assert all(reply.state == 'RUNNING' for reply in replies)
            async with asyncio.timeout(3):
                while not Path('child.json').exists(): await asyncio.sleep(0.01)
            child_environment = json.loads(Path('child.json').read_text())
            assert child_environment['EXECUTION_ID'] == 'execution'
            assert child_environment['NODE_ID'] == 'node' and child_environment['PLUGIN_MODE'] == 'server'
            assert 'AGENT_ONLY_SECRET' not in child_environment
            assert Path('spawns').read_text().splitlines() == [str(controller._process.pid)]
            await rejected(client.start('different-start'),grpc.StatusCode.ALREADY_EXISTS)
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
'''


def test_generated_control_roles_and_process_lifecycle(tmp_path: Path):
    manifest = ServiceManifest.model_validate({'service':{'name':'control_agent','plugin_agent':{'enabled':True}}})
    output = tmp_path/'generated'
    PluginAgentGenerator(manifest,output).generate()
    (output/'plugin_control_client.py').write_text(env.get_template('services/plugin_control_client.py.j2').render())
    result = subprocess.run([sys.executable,'-c',SCENARIO],cwd=tmp_path,
        env=dict(os.environ,PYTHONPATH=str(tmp_path)),capture_output=True,text=True,timeout=30)
    assert result.returncode == 0,result.stdout+result.stderr
