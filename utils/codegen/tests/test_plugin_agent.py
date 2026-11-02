"""Generated assignment-scoped agent with actual transport and injected async ports."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.plugin_agent import PluginAgentGenerator
from generators.plugins.sidecar_client import SidecarClientGenerator
from config.plugin_models import PluginManifest, PluginConfig

ROOT = Path(__file__).resolve().parents[3]

SCENARIO = r'''
import asyncio
from types import SimpleNamespace
import grpc
from src.policy import AssignmentPolicy
from generated.plugin_agent.proxy import PluginAgentProxy
from generated.plugin_agent.server import create_server
from generated.scoped_server import ServerConfig
from generated.sidecar_client import SidecarAgentClient
from generated.protos.plugins import index_pb2 as pb
from generated.protos.plugins import index_pb2_grpc as rpc

class Backends:
    def __init__(self): self.calls=[]
    def check(self, method, fields):
        assert fields['owner_id'] == 'owner-only'
        assert fields['execution_id'] == 'exec' and fields['node_id'] == 'node'
        self.calls.append(method)
    async def call_llm(self, **fields):
        self.check('llm',fields)
        yield 'real '
        yield 'result'
    async def transcribe(self, **fields):
        self.check('stt',fields)
        assert fields['audio']==b'audio'
        return 'spoken text'
    async def read_file(self, **fields):
        self.check('file',fields)
        assert fields['file_id']=='file-owned'
        yield b'data'
    async def fetch_prompt(self, **fields):
        self.check('prompt',fields)
        return dict(prompt_id='prompt-owned',system_prompt='system',user_prompt_template='text',rendered_user_prompt='text')
    async def save_artifact(self, **fields):
        self.check('artifact',fields)
        assert fields['data']==b'result'
        return dict(file_id='saved-file',size_bytes=6)
    async def report_progress(self, **fields): self.check('progress',fields)
    async def report_metrics(self, **fields): self.check('metrics',fields)
    async def log(self, **fields): self.check('log',fields)

async def expect(awaitable, code):
    try: await awaitable
    except grpc.aio.AioRpcError as error:
        assert error.code()==code, error
        assert 'secret backend detail' not in error.details()
    else: raise AssertionError('Expected scoped denial')

async def collect(call): return [part async for part in call]

async def main():
    manifest={'plugin':{'name':'test_plugin','permissions':{
        'llm':{'enabled':True,'allowed_models':['small-model'],'allowed_purposes':['transform','stt']},
        'storage':{'enabled':True}},'outputs':[{'name':'result','type':'artifact/file'}]}}
    policy=AssignmentPolicy.from_manifest(execution_id='exec',node_id='node',owner_id='owner-only',
        manifest=manifest,file_ids=['file-owned'],prompt_ids=['prompt-owned'])
    backends=Backends()
    proxy=PluginAgentProxy(policy,backends,timeout=0.1)
    config=ServerConfig('test-token','exec','node','127.0.0.1:0')
    server,port=create_server(config,proxy)
    await server.start()
    address=f'127.0.0.1:{port}'
    authorized=(('authorization','Bearer test-token'),('x-execution-id','exec'),('x-node-id','node'))
    try:
        async with grpc.aio.insecure_channel(address) as channel:
            stub=rpc.PluginAgentServiceStub(channel)
            await expect(collect(stub.CallLLM(pb.LLMRequest(model='small-model'))),grpc.StatusCode.UNAUTHENTICATED)
            async def artifact(): yield pb.SaveArtifactChunk(metadata=pb.ArtifactMetadata(artifact_name='result'))
            await expect(stub.SaveArtifact(artifact()),grpc.StatusCode.UNAUTHENTICATED)
            wrong=(('authorization','Bearer test-token'),('x-execution-id','other'),('x-node-id','node'))
            await expect(stub.ReportProgress(pb.ReportProgressRequest(percent=1),metadata=wrong),grpc.StatusCode.PERMISSION_DENIED)
            assert backends.calls==[]
            response=await collect(stub.CallLLM(pb.LLMRequest(model='small-model',purpose='transform',max_tokens=100,
                messages=[pb.LLMMessage(role='user',content='input')]),metadata=authorized))
            assert ''.join(item.delta_content for item in response)=='real result' and response[-1].is_finished
            await expect(collect(stub.CallLLM(pb.LLMRequest(model='forbidden',purpose='transform'),metadata=authorized)),grpc.StatusCode.PERMISSION_DENIED)
            await expect(collect(stub.ReadFile(pb.ReadFileRequest(file_id='other-owner',chunk_size_bytes=4),metadata=authorized)),grpc.StatusCode.PERMISSION_DENIED)
            await expect(stub.FetchPrompt(pb.FetchPromptRequest(prompt_id='other-owner'),metadata=authorized),grpc.StatusCode.PERMISSION_DENIED)
            async def denied_artifact():
                yield pb.SaveArtifactChunk(metadata=pb.ArtifactMetadata(artifact_name='undeclared',filename='a.txt',content_type='text/plain'))
            await expect(stub.SaveArtifact(denied_artifact(),metadata=authorized),grpc.StatusCode.PERMISSION_DENIED)
        # Exercise the generated client against the real agent boundary.
        import os
        os.environ['LECTIFY_AGENT_TOKEN']='test-token'
        async with SidecarAgentClient(address,execution_id='exec',node_id='node') as client:
            assert await client.transcribe(b'audio',model='small-model',language='ru')=='spoken text'
            assert [item async for item in client.read_file('file-owned',4)]==[b'data']
            assert (await client.fetch_prompt('prompt-owned'))['system_prompt']=='system'
            assert (await client.save_artifact('result','a.txt','text/plain',b'result'))['file_id']=='saved-file'
            await client.report_progress(5,'started')
            await client.report_metrics({'latency':1},{'items':1})
            await client.log('info','working')
        assert set(backends.calls)=={'llm','stt','file','prompt','artifact','progress','metrics','log'}
        async def denied(**fields):
            raise grpc.aio.AioRpcError(grpc.StatusCode.PERMISSION_DENIED,(),(),'secret backend detail')
        proxy.backends=SimpleNamespace(report_progress=denied)
        async with grpc.aio.insecure_channel(address) as channel:
            stub=rpc.PluginAgentServiceStub(channel)
            await expect(stub.ReportProgress(pb.ReportProgressRequest(percent=1),metadata=authorized),grpc.StatusCode.PERMISSION_DENIED)
        # Missing backend port cannot pretend a durable operation succeeded.
        proxy.backends=SimpleNamespace()
        async with grpc.aio.insecure_channel(address) as channel:
            stub=rpc.PluginAgentServiceStub(channel)
            await expect(stub.ReportProgress(pb.ReportProgressRequest(percent=1),metadata=authorized),grpc.StatusCode.UNAVAILABLE)
    finally: await server.stop(0)
asyncio.run(main())
'''


def test_scoped_plugin_agent_real_rpc(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(base,'get_settings',lambda:SimpleNamespace(POSTGRES_PORT=5432))
    monkeypatch.setattr(base,'get_context_manager',lambda:SimpleNamespace(get_service_context=lambda name:ServiceContext()))
    manifest=ServiceManifest.model_validate({'service':{'name':'agent_test','plugin_agent':{'enabled':True}}})
    PluginAgentGenerator(manifest,tmp_path/'generated').generate()
    SidecarClientGenerator(PluginManifest(plugin=PluginConfig(name='test_plugin')),tmp_path/'generated').generate()
    shutil.copytree(ROOT/'services/orchestrator/agent/src',tmp_path/'src')
    result=subprocess.run([sys.executable,'-c',SCENARIO],cwd=tmp_path,
                          env=dict(os.environ,PYTHONPATH=str(tmp_path)),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
