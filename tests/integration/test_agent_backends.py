"""Generated agent ports call actual service RPCs using delegated owner credentials."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from config.models import ServiceManifest
from config.plugin_models import PluginConfig, PluginManifest
from context import ServiceContext
from generators.services import base
from generators.services.grpc_client import GrpcClientGenerator
from generators.services.plugin_agent import PluginAgentGenerator
from generators.plugins.sidecar_client import SidecarClientGenerator

ROOT = Path(__file__).resolve().parents[2]

SCENARIO = r'''
import asyncio
import hashlib
import os
import grpc
from src.backends import RPCBackends
from generated.plugin_agent.proxy import PluginAgentProxy
from generated.plugin_agent.server import create_server
from generated.scoped_server import ServerConfig
from generated.sidecar_client import SidecarAgentClient
from src.policy import AssignmentPolicy
from generated.protos.clients.api_auth import index_pb2 as auth_pb
from generated.protos.clients.api_auth import index_pb2_grpc as auth_rpc
from generated.protos.clients.api_file import index_pb2 as file_pb
from generated.protos.clients.api_file import index_pb2_grpc as file_rpc
from generated.protos.clients.api_prompt import index_pb2 as prompt_pb
from generated.protos.clients.api_prompt import index_pb2_grpc as prompt_rpc
from generated.protos.clients.plugins_provider import index_pb2 as provider_pb
from generated.protos.clients.plugins_provider import index_pb2_grpc as provider_rpc
from generated.protos.clients.orchestrator import index_pb2 as orchestration_pb
from generated.protos.clients.orchestrator import index_pb2_grpc as orchestration_rpc

calls=[]
def owner(context):
    assert dict(context.invocation_metadata())['x-user-authorization']=='Bearer delegated-token'
class Auth(auth_rpc.AuthServiceServicer):
    async def Authenticate(self,request,context):
        calls.append('auth')
        return auth_pb.AuthenticateResponse(valid=True,user_id='owner' if request.access_token=='delegated-token' else 'other')
class File(file_rpc.FileServiceServicer):
    corrupt=False
    async def Download(self,request,context):
        owner(context);calls.append('read')
        assert request.id=='owned-file'
        data=b'original file bytes'
        yield file_pb.DownloadFrame(sequence=0,metadata=file_pb.File(id=request.id,size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        yield file_pb.DownloadFrame(sequence=1,chunk=b'CORRUPT' if self.corrupt else data)
        yield file_pb.DownloadFrame(sequence=2,chunk=b'',is_last=True)
    async def Upload(self,requests,context):
        owner(context);calls.append('save')
        frames=[frame async for frame in requests]
        assert frames[0].WhichOneof('data')=='metadata' and frames[0].sequence==0
        assert [frame.sequence for frame in frames]==list(range(len(frames))) and frames[-1].is_last
        data=b''.join(frame.chunk for frame in frames[1:])
        assert len(data)==frames[0].metadata.size_bytes
        assert hashlib.sha256(data).hexdigest()==frames[0].metadata.sha256
        return file_pb.File(id='saved-file',size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
class Prompt(prompt_rpc.PromptServiceServicer):
    async def GetPrompt(self,request,context):
        owner(context);calls.append('prompt')
        return prompt_pb.Prompt(id=request.id,user_prompt_template='Hello {name}')
    async def RenderPrompt(self,request,context):
        owner(context)
        assert request.variables['name']=='World'
        return prompt_pb.RenderPromptResponse(system_prompt='system',user_prompt='Hello World')
class Provider(provider_rpc.ProviderServiceServicer):
    async def CallLLM(self,request,context):
        owner(context);calls.append('llm')
        assert request.owner_id=='owner' and request.execution_id=='exec' and request.node_id=='node'
        yield provider_pb.LLMResponse(delta_content='Actual model text',is_finished=True)
    async def Transcribe(self,requests,context):
        owner(context);calls.append('stt')
        frames=[frame async for frame in requests]
        assert frames[0].metadata.owner_id=='owner' and frames[0].metadata.content_type=='audio/wav'
        assert frames[-1].is_last and frames[-1].sequence==len(frames)-1
        assert b''.join(frame.chunk for frame in frames[1:])==b'RIFF0000WAVEaudio'
        return provider_pb.TranscribeResponse(text='Actual transcript')

class Orchestrator(orchestration_rpc.OrchestratorServiceServicer):
    reject=False
    events=[]
    async def ReportNodeEvent(self,request,context):
        owner(context)
        assert request.execution_id=='exec' and request.node_id=='node'
        assert request.owner=='lease-worker' and request.fence==3 and request.report_token=='report-secret'
        self.events.append(request.kind)
        return orchestration_pb.ReportNodeEventResponse(accepted=not self.reject,event_id=request.event_id,sequence=1)

async def reject(awaitable, code):
    try: await awaitable
    except grpc.aio.AioRpcError as error: assert error.code()==code,error
    else: raise AssertionError('Expected failure')
async def read(client): return [item async for item in client.read_file('owned-file',4)]

async def main():
    servers=[]
    file=File()
    orchestrator=Orchestrator()
    for name,servicer,register in [('AUTH',Auth(),auth_rpc.add_AuthServiceServicer_to_server),
        ('FILE',file,file_rpc.add_FileServiceServicer_to_server),
        ('PROMPT',Prompt(),prompt_rpc.add_PromptServiceServicer_to_server),
        ('PROVIDER',Provider(),provider_rpc.add_ProviderServiceServicer_to_server),
        ('ORCHESTRATOR',orchestrator,orchestration_rpc.add_OrchestratorServiceServicer_to_server)]:
        server=grpc.aio.server();register(servicer,server)
        port=server.add_insecure_port('127.0.0.1:0');await server.start();servers.append(server)
        os.environ['LECTIFY_AGENT_'+name+'_ADDRESS']=f'127.0.0.1:{port}'
    events=[]
    async def sink(**scope):
        assert scope['owner_id']=='owner' and scope['execution_id']=='exec'
        events.append(scope)
    backends=RPCBackends('delegated-token',lease_owner='lease-worker',fence=3,report_token='report-secret')
    policy=AssignmentPolicy(execution_id='exec',node_id='node',owner_id='owner',plugin_name='test',
        llm_enabled=True,storage_enabled=True,models=['small-model'],purposes=['transform','stt'],
        file_ids=['owned-file'],prompt_ids=['owned-prompt'],artifact_names=['result'])
    server,port=create_server(ServerConfig('agent-token','exec','node','127.0.0.1:0'),PluginAgentProxy(policy,backends))
    await server.start();servers.append(server)
    os.environ['LECTIFY_AGENT_TOKEN']='agent-token'
    try:
        async with SidecarAgentClient(f'127.0.0.1:{port}',execution_id='exec',node_id='node') as client:
            assert b''.join(await read(client))==b'original file bytes'
            assert (await client.fetch_prompt('owned-prompt',{'name':'World'}))['rendered_user_prompt']=='Hello World'
            assert (await client.save_artifact('result','result.txt','text/plain',b'output'))['file_id']=='saved-file'
            assert (await client.save_artifact('result','empty.txt','text/plain',b''))['size_bytes']==0
            assert ''.join([item async for item in client.call_llm('small-model',[{'role':'user','content':'input'}],purpose='transform')])=='Actual model text'
            assert await client.transcribe(b'RIFF0000WAVEaudio',model='small-model',language='en')=='Actual transcript'
            await client.report_progress(50,'working');assert 'progress' in orchestrator.events
            orchestrator.reject=True
            await reject(client.report_progress(60,'rejected'),grpc.StatusCode.UNAVAILABLE)
            orchestrator.reject=False
            file.corrupt=True
            await reject(read(client),grpc.StatusCode.UNAVAILABLE)
            file.corrupt=False
            before=len(calls)
            backends._access_token='wrong-owner-token'
            await reject(read(client),grpc.StatusCode.PERMISSION_DENIED)
            assert calls[before:]==['auth']
    finally:
        for server in servers: await server.stop(0)
asyncio.run(main())
'''


def test_agent_real_backend_rpc_mapping_and_delegated_owner(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(base,'get_settings',lambda:SimpleNamespace(POSTGRES_PORT=5432))
    monkeypatch.setattr(base,'get_context_manager',lambda:SimpleNamespace(get_service_context=lambda name:ServiceContext()))
    manifest=ServiceManifest.model_validate({'service':{'name':'agent_backends','plugin_agent':{'enabled':True},'grpc_client':{'enabled':True,'services':['api_auth','api_file','api_prompt','plugins_provider','orchestrator']}}})
    GrpcClientGenerator(manifest,tmp_path/'generated').generate()
    PluginAgentGenerator(manifest,tmp_path/'generated').generate()
    SidecarClientGenerator(PluginManifest(plugin=PluginConfig(name='test')),tmp_path/'generated').generate()
    shutil.copytree(ROOT/'services/orchestrator/agent/src',tmp_path/'src')
    result=subprocess.run([sys.executable,'-c',SCENARIO],cwd=tmp_path,
        env=dict(os.environ,PYTHONPATH=str(tmp_path)),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
