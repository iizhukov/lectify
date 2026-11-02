"""Create the shared scenario library through authenticated backend gRPC APIs."""
import asyncio
import json
from pathlib import Path
import sys
import yaml
from google.protobuf.json_format import ParseDict

sys.path.insert(0,'/app/services/tools/client')
from generated.grpc_client.grpc_clients import GrpcClients
from generated.protos.clients.api_auth import index_pb2 as auth_pb, index_pb2_grpc as auth_rpc
from generated.protos.clients.api_prompt import index_pb2 as prompt_pb, index_pb2_grpc as prompt_rpc
from generated.protos.clients.api_workflow import index_pb2 as wf_pb, index_pb2_grpc as wf_rpc
from generated.protos.clients.orchestrator import index_pb2 as orch_pb, index_pb2_grpc as orch_rpc
from backend import PLUGINS
from workflow_catalog import PROMPTS,build


async def main():
    clients=GrpcClients(source_service='tools_client')
    try:
        secrets=json.loads(Path('/run/config/secrets.json').read_text())
        auth=auth_rpc.AuthServiceStub(clients.channel('api_auth'))
        login=await auth.Login(auth_pb.LoginRequest(username='admin',password=secrets['admin']),timeout=15)
        metadata=(('x-user-authorization','Bearer '+login.access_token),)
        registry=orch_rpc.OrchestratorServiceStub(clients.channel('orchestrator'))
        for relative in PLUGINS.values():
            manifest=yaml.safe_load((Path('/app/plugins')/relative/'plugin.yaml').read_text())
            await registry.RegisterPluginManifest(orch_pb.RegisterPluginManifestRequest(plugin_id=manifest['plugin']['name'],
                version=manifest['plugin']['version'],manifest_yaml=json.dumps(manifest)),metadata=metadata,timeout=20)
        prompts=prompt_rpc.PromptServiceStub(clients.channel('api_prompt'))
        workflows=wf_rpc.WorkflowServiceStub(clients.channel('api_workflow'))
        known={}; offset=0
        while True:
            page=await prompts.ListPrompts(prompt_pb.ListPromptsRequest(page_size=100,offset=offset),metadata=metadata,timeout=20)
            known.update({row.name:row.id for row in page.prompts if not row.owner_id})
            if not page.has_more: break
            offset+=100
        prompt_ids={}
        for key,spec in PROMPTS.items():
            id=known.get(spec['name'])
            if id is None:
                saved=await prompts.CreatePrompt(prompt_pb.CreatePromptRequest(**spec,global_prompt=True),metadata=metadata,timeout=20)
                id=saved.id
            prompt_ids[key]=id
        known={}; offset=0
        while True:
            page=await workflows.ListWorkflows(wf_pb.ListRequest(page_size=100,offset=offset),metadata=metadata,timeout=20)
            known.update({row.name:row.id for row in page.workflows if not row.owner_id})
            if not page.next_offset: break
            offset=page.next_offset
        for spec in build(prompt_ids):
            id=known.get(spec['name'])
            if id is None:
                saved=await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name=spec['name'],description=spec['description'],
                    graph=ParseDict(spec['graph'],wf_pb.WorkflowGraph()),global_workflow=True,is_public=True),metadata=metadata,timeout=20)
                id=saved.id
                print('CREATED: '+spec['name']+' '+id)
            else: print('EXISTS: '+spec['name']+' '+id)
    finally: await clients.close_all()


if __name__=='__main__': asyncio.run(main())
