"""gRPC half of the local crash/pause/retry probe; host actions use a narrow pipe protocol."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import uuid
import grpc
sys.path.insert(0,'/app/services/tools/client')
from generated.grpc_client.grpc_clients import GrpcClients
from generated.protos.clients.api_auth import index_pb2 as auth_pb,index_pb2_grpc as auth_rpc
from generated.protos.clients.api_execution import index_pb2 as ex_pb,index_pb2_grpc as ex_rpc
from generated.protos.clients.api_workflow import index_pb2 as wf_pb,index_pb2_grpc as wf_rpc
from generated.protos.clients.api_file import index_pb2 as file_pb,index_pb2_grpc as file_rpc
from seed import main as seed_library


async def host(action,value):
    print('HOST '+action+' '+value,flush=True)
    response=await asyncio.to_thread(sys.stdin.readline)
    if not response: raise RuntimeError('Recovery host controller disconnected')
    return json.loads(response)


async def main():
    if not json.loads(Path('/run/config/mode.json').read_text()).get('offline_test_provider'):
        raise RuntimeError('Crash probe requires explicit offline provider')
    await seed_library()
    clients=GrpcClients(source_service='tools_client')
    try:
        secrets=json.loads(Path('/run/config/secrets.json').read_text())
        auth=auth_rpc.AuthServiceStub(clients.channel('api_auth'))
        login=await auth.Login(auth_pb.LoginRequest(username='admin',password=secrets['admin']),timeout=15)
        metadata=(('x-user-authorization','Bearer '+login.access_token),)
        workflows=wf_rpc.WorkflowServiceStub(clients.channel('api_workflow'))
        executions=ex_rpc.ExecutionServiceStub(clients.channel('api_execution'))
        files=file_rpc.FileServiceStub(clients.channel('api_file'))

        async def start(prefix):
            text=prefix+' '+uuid.uuid4().hex
            workflow=await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name='Local recovery probe',graph=wf_pb.WorkflowGraph(
                nodes=[wf_pb.GraphNode(id='source',plugin_id='text_input',plugin_version='0.1.0',input_mapping=[wf_pb.InputMapping(
                    target_field='value',source='input.text',transform='passthrough')]),
                    wf_pb.GraphNode(id='llm',plugin_id='llm_request',plugin_version='1.0.0')],
                edges=[wf_pb.GraphEdge(from_node_id='source',from_output='text',to_node_id='llm',to_input='text')])),metadata=metadata,timeout=20)
            run=await executions.StartWorkflow(ex_pb.StartWorkflowRequest(workflow_id=workflow.id,expected_version=workflow.version,
                request_key=uuid.uuid4().hex,initial_inputs={'text':text}),metadata=metadata,timeout=30)
            return run.execution_id,text

        async def status(id,predicate):
            async with asyncio.timeout(180):
                while True:
                    try:
                        value=await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=id),metadata=metadata,timeout=10)
                        if predicate(value): return value
                        if value.state in ('EXECUTION_STATE_FAILED','EXECUTION_STATE_CANCELLED'):
                            raise AssertionError('Unexpected terminal state: '+value.state+' '+value.error_message)
                    except grpc.aio.AioRpcError as error:
                        if error.code() not in (grpc.StatusCode.UNAVAILABLE,grpc.StatusCode.DEADLINE_EXCEEDED): raise
                    await asyncio.sleep(.4)

        async def active(id,text):
            async with asyncio.timeout(60):
                while not (await host('OBSERVE',hashlib.sha256(text.encode()).hexdigest()))['calls']:
                    await asyncio.sleep(.3)
            await status(id,lambda value:any(node.node_id=='source' and node.state=='NODE_STATE_COMPLETED' for node in value.nodes))

        async def result(id,text):
            value=await status(id,lambda value:value.state=='EXECUTION_STATE_COMPLETED')
            file_id=next(node for node in value.nodes if node.node_id=='llm').output_artifacts['result_file']
            frames=[frame async for frame in files.Download(file_pb.FileRequest(id=file_id),metadata=metadata,timeout=20)]
            assert frames[-1].is_last
            assert b''.join(frame.chunk for frame in frames if frame.WhichOneof('data')=='chunk')==('LOCAL TEST RESPONSE: '+text).encode()
            evidence=await host('EVIDENCE',id)
            assert evidence['source_launches']==1,evidence
            return evidence

        id,text=await start('TEST_FAIL_ONCE:')
        evidence=await result(id,text)
        assert evidence['llm_launches']==2 and evidence['automatic_retries']==1,evidence
        print('PASS: transient provider failure → bounded automatic retry → replayed source → saved result',flush=True)

        id,text=await start('TEST_FAIL_THREE:')
        await status(id,lambda value:value.state=='EXECUTION_STATE_FAILED')
        evidence=await host('EVIDENCE',id)
        assert evidence['llm_launches']==3 and evidence['automatic_retries']==2,evidence
        retry=await executions.RetryNode(ex_pb.RetryNodeRequest(execution_id=id,node_id='llm'),metadata=metadata,timeout=30)
        assert retry.success
        evidence=await result(id,text)
        assert evidence['llm_launches']==4,evidence
        print('PASS: three provider failures → exhausted automatic budget → manual RetryNode → completed; source launched once',flush=True)

        id,text=await start('TEST_DELAY:')
        await active(id,text)
        assert (await executions.Pause(ex_pb.ExecutionRequest(execution_id=id),metadata=metadata,timeout=45)).success
        paused=await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=id),metadata=metadata,timeout=15)
        assert paused.state=='EXECUTION_STATE_PAUSED'
        assert all(node.state in ('NODE_STATE_COMPLETED','NODE_STATE_PENDING') for node in paused.nodes)
        evidence=await host('EVIDENCE',id)
        assert evidence['source_ready'] and evidence['source_launches']==1,evidence
        assert (await executions.Resume(ex_pb.ExecutionRequest(execution_id=id),metadata=metadata,timeout=30)).success
        evidence=await result(id,text)
        assert evidence['llm_launches']==2,evidence
        print('PASS: pause during real HTTP request → persisted PAUSED/fence revocation → resume/replay → correct S3 result',flush=True)

        id,text=await start('TEST_DELAY:')
        await active(id,text)
        assert (await host('RESTART',id))['restarted']
        evidence=await result(id,text)
        assert evidence['llm_launches']==2 and evidence['automatic_retries']==0,evidence
        async with asyncio.timeout(60):
            while (await host('EVIDENCE',id))['unclean_attempts']:
                await asyncio.sleep(1)
        print('PASS: SIGKILL orchestrator → DB lease takeover → completed source replay → correct result; stale containers reconciled',flush=True)
    finally: await clients.close_all()


if __name__=='__main__': asyncio.run(main())
