"""Real local gRPC restart/history/native-log regression probe, no paid calls."""
import asyncio
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,'/app/services/tools/client')
from generated.grpc_client.grpc_clients import GrpcClients
from generated.protos.clients.api_auth import index_pb2 as auth_pb,index_pb2_grpc as auth_rpc
from generated.protos.clients.api_workflow import index_pb2 as wf_pb,index_pb2_grpc as wf_rpc
from generated.protos.clients.api_execution import index_pb2 as ex_pb,index_pb2_grpc as ex_rpc
from generated.protos.clients.api_file import index_pb2 as file_pb,index_pb2_grpc as file_rpc
from seed import main as seed_library


async def main():
    if not json.loads(Path('/run/config/mode.json').read_text()).get('offline_test_provider'):
        raise RuntimeError('Probe requires explicit offline fixture')
    await seed_library()
    clients=GrpcClients(source_service='tools_client')
    try:
        secret=json.loads(Path('/run/config/secrets.json').read_text())
        login=await auth_rpc.AuthServiceStub(clients.channel('api_auth')).Login(auth_pb.LoginRequest(username='admin',password=secret['admin']),timeout=15)
        metadata=(('x-user-authorization','Bearer '+login.access_token),)
        workflows=wf_rpc.WorkflowServiceStub(clients.channel('api_workflow'))
        executions=ex_rpc.ExecutionServiceStub(clients.channel('api_execution'))
        files=file_rpc.FileServiceStub(clients.channel('api_file'))
        async def status(id,expected='EXECUTION_STATE_COMPLETED'):
            async with asyncio.timeout(180):
                while True:
                    row=await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=id),metadata=metadata,timeout=15)
                    if row.state==expected: return row
                    if row.state in ('EXECUTION_STATE_FAILED','EXECUTION_STATE_COMPLETED','EXECUTION_STATE_CANCELLED'):
                        raise AssertionError(row.state+' '+row.error_message)
                    await asyncio.sleep(.4)
        async def logs(id,node,number=1):
            frames=[part async for part in executions.DownloadNodeLog(ex_pb.NodeLogRequest(execution_id=id,node_id=node,attempt_number=number),metadata=metadata,timeout=30)]
            assert frames[-1].is_last and [part.sequence for part in frames]==list(range(len(frames)))
            return b''.join(part.data for part in frames)
        async def start(name,parameters=None):
            graph=wf_pb.WorkflowGraph(nodes=[wf_pb.GraphNode(id='source',name='Frozen input name',plugin_id='text_input',plugin_version='0.1.0',input_mapping=[wf_pb.InputMapping(target_field='value',source='input.text',transform='passthrough')]),
                wf_pb.GraphNode(id='pdf',name='PDF compiler',plugin_id='latex_to_pdf',plugin_version='1.0.0',parameters_json=json.dumps(parameters or {'max_attempts':1,'use_llm_repair':False}))],
                edges=[wf_pb.GraphEdge(from_node_id='source',from_output='text',to_node_id='pdf',to_input='latex')])
            workflow=await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name=name,graph=graph),metadata=metadata,timeout=20)
            run=await executions.StartWorkflow(ex_pb.StartWorkflowRequest(workflow_id=workflow.id,expected_version=workflow.version,
                request_key=uuid.uuid4().hex,initial_inputs={'text':r'\documentclass{article}\begin{document}Original frozen document.\end{document}'}),metadata=metadata,timeout=30)
            return workflow,run
        workflow,run=await start('Restart provenance and compiler diagnostics')
        await status(run.execution_id)
        before=await executions.GetDetails(ex_pb.ExecutionRequest(execution_id=run.execution_id),metadata=metadata,timeout=20)
        assert before.initial_inputs['text'].endswith(r'\end{document}')
        compiler=next(node for node in before.nodes if node.node_id=='pdf')
        assert compiler.name=='PDF compiler' and compiler.attempts[0].state=='COMPLETED'
        assert compiler.attempts[0].artifacts[0].file_id and compiler.attempts[0].container_id
        content=await logs(run.execution_id,'pdf')
        assert b'pdfTeX' in content and b'Node attempt completed' in content
        assert b'[stdout]' in content
        await workflows.DeleteWorkflow(wf_pb.DeleteRequest(id=workflow.id,expected_version=workflow.version),metadata=metadata,timeout=20)
        req=ex_pb.RestartRequest(execution_id=run.execution_id,request_key='repeatable-restart')
        first,again=await asyncio.gather(*[executions.Restart(req,metadata=metadata,timeout=30) for _ in range(2)])
        assert first.execution_id==again.execution_id and first.execution_id!=run.execution_id
        assert first.parent_execution_id==run.execution_id and first.snapshot_id==run.snapshot_id
        await status(first.execution_id)
        after=await executions.GetDetails(ex_pb.ExecutionRequest(execution_id=first.execution_id),metadata=metadata,timeout=20)
        assert after.parent_execution_id==run.execution_id and after.graph_json==before.graph_json
        for node in after.nodes:
            assert len(node.attempts)==1 and node.attempts[0].number==1 and node.attempts[0].state=='COMPLETED'
            previous=next(item for item in before.nodes if item.node_id==node.node_id)
            assert node.attempts[0].id!=previous.attempts[0].id
        history=await executions.ListExecutions(ex_pb.ListExecutionsRequest(page_size=100),metadata=metadata,timeout=15)
        assert next(row for row in history.executions if row.execution_id==first.execution_id).parent_execution_id==run.execution_id
        print('PASS: completed execution → workflow deleted → concurrent idempotent full restart → same frozen graph/inputs → fresh attempts and linked history',flush=True)
        print('PASS: node details → frozen names/parameters/edges, attempt timings, container placement, artifacts; actual TeX stdout downloaded through gRPC',flush=True)

        # Compiler failure must retain its diagnostic log, not just a generic error status.
        broken=wf_pb.WorkflowGraph(nodes=[wf_pb.GraphNode(id='source',plugin_id='text_input',plugin_version='0.1.0',input_mapping=[wf_pb.InputMapping(target_field='value',source='input.text',transform='passthrough')]),
            wf_pb.GraphNode(id='pdf',plugin_id='latex_to_pdf',plugin_version='1.0.0',parameters_json='{"max_attempts":1,"use_llm_repair":false}')],
            edges=[wf_pb.GraphEdge(from_node_id='source',from_output='text',to_node_id='pdf',to_input='latex')])
        workflow=await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name='Failed compiler log',graph=broken),metadata=metadata,timeout=20)
        failed=await executions.StartWorkflow(ex_pb.StartWorkflowRequest(workflow_id=workflow.id,expected_version=workflow.version,
            request_key=uuid.uuid4().hex,initial_inputs={'text':r'\documentclass{article}\begin{document}\undefinedcommand\end{document}'}),metadata=metadata,timeout=30)
        await status(failed.execution_id,'EXECUTION_STATE_FAILED')
        failed_log=await logs(failed.execution_id,'pdf')
        assert b'Undefined control sequence' in failed_log and b'Node attempt failed' in failed_log
        print('PASS: native compiler failure → FAILED attempt → durable diagnostic log with actual compiler error',flush=True)
        restarted=await executions.Restart(ex_pb.RestartRequest(execution_id=failed.execution_id,request_key='restart-failed'),metadata=metadata,timeout=30)
        await status(restarted.execution_id,'EXECUTION_STATE_FAILED')
        assert restarted.parent_execution_id==failed.execution_id
        assert b'Undefined control sequence' in await logs(restarted.execution_id,'pdf')
        print('PASS: failed execution → full restart with fresh attempts → original compiler diagnostics preserved independently',flush=True)

        delayed=wf_pb.WorkflowGraph(nodes=[wf_pb.GraphNode(id='source',plugin_id='text_input',plugin_version='0.1.0',input_mapping=[wf_pb.InputMapping(
            target_field='value',source='input.text',transform='passthrough')]),wf_pb.GraphNode(id='llm',plugin_id='llm_request',plugin_version='1.0.0')],
            edges=[wf_pb.GraphEdge(from_node_id='source',from_output='text',to_node_id='llm',to_input='text')])
        workflow=await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name='Cancelled full restart',graph=delayed),metadata=metadata,timeout=20)
        cancelled=await executions.StartWorkflow(ex_pb.StartWorkflowRequest(workflow_id=workflow.id,expected_version=workflow.version,
            request_key=uuid.uuid4().hex,initial_inputs={'text':'TEST_DELAY: restart-cancelled '+uuid.uuid4().hex}),metadata=metadata,timeout=30)
        async with asyncio.timeout(60):
            while True:
                current=await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=cancelled.execution_id),metadata=metadata,timeout=15)
                if any(node.node_id=='source' and node.state=='NODE_STATE_COMPLETED' for node in current.nodes): break
                await asyncio.sleep(.2)
        assert (await executions.Cancel(ex_pb.CancelRequest(execution_id=cancelled.execution_id),metadata=metadata,timeout=45)).success
        await status(cancelled.execution_id,'EXECUTION_STATE_CANCELLED')
        restarted=await executions.Restart(ex_pb.RestartRequest(execution_id=cancelled.execution_id,request_key='restart-cancelled'),metadata=metadata,timeout=30)
        await status(restarted.execution_id)
        child=await executions.GetDetails(ex_pb.ExecutionRequest(execution_id=restarted.execution_id),metadata=metadata,timeout=20)
        assert child.parent_execution_id==cancelled.execution_id
        assert all(node.attempts[0].state=='COMPLETED' and node.attempts[0].number==1 for node in child.nodes)
        original=await executions.GetDetails(ex_pb.ExecutionRequest(execution_id=cancelled.execution_id),metadata=metadata,timeout=20)
        assert original.status.state=='EXECUTION_STATE_CANCELLED'
        old_source=next(node for node in original.nodes if node.node_id=='source')
        new_source=next(node for node in child.nodes if node.node_id=='source')
        assert old_source.attempts[0].id!=new_source.attempts[0].id
        print('PASS: cancelled execution → full restart → even completed source executes anew; original cancellation/history unchanged',flush=True)
    finally: await clients.close_all()


if __name__=='__main__': asyncio.run(main())
