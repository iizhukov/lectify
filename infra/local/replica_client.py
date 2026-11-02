"""Exercise two local orchestrator endpoints against the same execution/DB/host agent."""
import asyncio
import json
from pathlib import Path
import sys
import uuid
import grpc
sys.path.insert(0,'/app/services/tools/client')
from generated.grpc_client.grpc_clients import GrpcClients,_split_interceptors
from generated.ticket_auth.interceptor import TicketAuthClientInterceptor
from generated.observability.client import TracingClientInterceptor
from generated.transport import TLSConfig
from generated.protos.clients.api_auth import index_pb2 as auth_pb,index_pb2_grpc as auth_rpc
from generated.protos.clients.api_file import index_pb2 as file_pb,index_pb2_grpc as file_rpc
from generated.protos.clients.orchestrator import index_pb2 as pb,index_pb2_grpc as rpc
from seed import main as seed_library


async def main():
    if not json.loads(Path('/run/config/mode.json').read_text()).get('offline_test_provider'):
        raise RuntimeError('Replica probe requires offline test provider')
    await seed_library()
    clients=GrpcClients(source_service='tools_client'); channels=[]; resources=[]
    try:
        secrets=json.loads(Path('/run/config/secrets.json').read_text())
        login=await auth_rpc.AuthServiceStub(clients.channel('api_auth')).Login(auth_pb.LoginRequest(
            username='admin',password=secrets['admin']),timeout=15)
        metadata=(('x-user-authorization','Bearer '+login.access_token),)
        tls=TLSConfig.from_env('LECTIFY_GRPC_CLIENT_TLS')
        credentials=grpc.ssl_channel_credentials(tls.roots,tls.private_key,tls.certificate)
        for endpoint in sys.argv[1:]:
            interceptors=[TracingClientInterceptor(),TicketAuthClientInterceptor('tools_client','orchestrator')]
            resources.extend(item for item in interceptors if hasattr(item,'close'))
            # Endpoints are operator-inspected container IPs. Verify the expected
            # orchestrator certificate identity on both, never an arbitrary name.
            channel=grpc.aio.secure_channel(endpoint,credentials,options=[('grpc.ssl_target_name_override','orchestrator')],
                interceptors=_split_interceptors(interceptors))
            channels.append(channel)
        assert len(channels)==2
        await asyncio.gather(*[asyncio.wait_for(channel.channel_ready(),30) for channel in channels])
        stubs=[rpc.OrchestratorServiceStub(channel) for channel in channels]
        id=str(uuid.uuid4()); value='TEST_DELAY: replica '+uuid.uuid4().hex
        request=pb.StartExecutionRequest(execution_id=id,workflow_id='local-replica-probe',initial_inputs={'text':value},graph=pb.WorkflowGraph(
            nodes=[pb.WorkflowNode(id='source',plugin_id='text_input',plugin_version='0.1.0',input_mapping_json=json.dumps([
                dict(target_field='value',source='input.text',transform='passthrough')])),
                pb.WorkflowNode(id='llm',plugin_id='llm_request',plugin_version='1.0.0')],
            edges=[pb.WorkflowEdge(from_node_id='source',from_output='text',to_node_id='llm',to_input='text')]))
        results=await asyncio.gather(*[stub.StartExecution(request,metadata=metadata,timeout=30) for stub in stubs])
        assert all(result.execution_id==id for result in results)
        async def status(predicate):
            async with asyncio.timeout(180):
                while True:
                    row=await stubs[0].GetExecutionStatus(pb.GetExecutionStatusRequest(execution_id=id),metadata=metadata,timeout=15)
                    if predicate(row): return row
                    assert row.state not in (pb.EXECUTION_STATE_FAILED,pb.EXECUTION_STATE_CANCELLED),row.error_message
                    await asyncio.sleep(.4)
        await status(lambda row:any(node.node_id=='source' and node.state==pb.NODE_STATE_COMPLETED for node in row.nodes))
        assert (await stubs[1].PauseExecution(pb.PauseExecutionRequest(execution_id=id),metadata=metadata,timeout=45)).success
        paused=await stubs[0].GetExecutionStatus(pb.GetExecutionStatusRequest(execution_id=id),metadata=metadata,timeout=15)
        assert paused.state==pb.EXECUTION_STATE_PAUSED
        assert (await stubs[0].ResumeExecution(pb.ResumeExecutionRequest(execution_id=id),metadata=metadata,timeout=45)).success
        completed=await status(lambda row:row.state==pb.EXECUTION_STATE_COMPLETED)
        file_id=next(node for node in completed.nodes if node.node_id=='llm').output_artifacts['result_file']
        frames=[part async for part in file_rpc.FileServiceStub(clients.channel('api_file')).Download(file_pb.FileRequest(id=file_id),metadata=metadata,timeout=20)]
        assert b''.join(part.chunk for part in frames if part.WhichOneof('data')=='chunk')==('LOCAL TEST RESPONSE: '+value).encode()
        print('EXECUTION '+id,flush=True)
    finally:
        for channel in channels: await channel.close()
        for resource in resources: await resource.close()
        await clients.close_all()


if __name__=='__main__': asyncio.run(main())
