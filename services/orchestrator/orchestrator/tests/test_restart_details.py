import asyncio
import json
from types import SimpleNamespace
import grpc
import pytest
from sqlalchemy import select
from generated.protos.server import index_pb2 as pb
from generated.stream_router import StreamChunkData as Frame
from generated.testing.context import MockServicerContext,MockRpcError
from src.models import WorkflowExecutionModel as Execution,WorkflowNodeAttemptModel as Attempt,WorkflowNodeExecutionModel as Node
from src.service import OrchestratorServiceImpl


def context(user='owner'):
    result=MockServicerContext(); result.lectify_principal=SimpleNamespace(user_id=user,is_admin=False)
    return result


class Echo:
    supports_streaming=True
    def __init__(self): self.calls=[]
    async def stream_node(self,*,node,inputs,**kwargs):
        data=b''.join([frame.payload async for frame in inputs])
        self.calls.append((node['parameters'],data))
        yield Frame('text',data); yield Frame('text',b'',sequence=1,is_last=True)


async def finished(service):
    await asyncio.wait_for(asyncio.gather(*list(service._execution_tasks.values())),5)


async def original(service):
    result=await service.StartExecution(pb.StartExecutionRequest(execution_id='original',workflow_id='frozen-snapshot',
        graph=pb.WorkflowGraph(nodes=[pb.WorkflowNode(id='echo',plugin_id='echo',plugin_version='1.0.0',
            parameters_json='{"setting":"original"}',input_mapping_json=json.dumps([
                dict(target_field='value',source='input.text',transform='passthrough')]))]),initial_inputs={'text':'saved input'}),context())
    await finished(service)
    return result.execution_id


@pytest.mark.asyncio
@pytest.mark.parametrize('state',['COMPLETED','FAILED','CANCELLED'])
async def test_full_restart_is_new_linked_idempotent_and_runs_all_nodes(test_session,state):
    dispatcher=Echo(); service=OrchestratorServiceImpl(container_manager=dispatcher)
    id=await original(service)
    row=await test_session.get(Execution,id); row.state=state; await test_session.commit()
    request=pb.RestartExecutionRequest(execution_id=id,request_key='one restart')
    replica=OrchestratorServiceImpl(container_manager=dispatcher)
    first,second=await asyncio.gather(service.RestartExecution(request,context()),replica.RestartExecution(request,context()))
    assert first.execution_id==second.execution_id and first.execution_id!=id
    assert first.parent_execution_id==id and first.workflow_id=='frozen-snapshot'
    await asyncio.gather(finished(service),finished(replica))
    child=await test_session.get(Execution,first.execution_id)
    assert child.state=='COMPLETED' and child.parent_execution_id==id
    await test_session.refresh(row); assert row.state==state
    assert dispatcher.calls==[({'setting':'original'},b'saved input')]*2
    details=await service.GetExecutionDetails(pb.GetExecutionStatusRequest(execution_id=child.id),context())
    assert details.parent_execution_id==id and details.initial_inputs=={'text':'saved input'}
    assert json.loads(details.nodes[0].parameters_json)=={'setting':'original'}
    assert len(details.nodes[0].attempts)==1 and details.nodes[0].attempts[0].state=='COMPLETED'
    assert len(list(await test_session.scalars(select(Attempt).where(Attempt.execution_id==id))))==1
    another=await service.RestartExecution(pb.RestartExecutionRequest(execution_id=id,request_key='second restart'),context())
    await finished(service); assert another.execution_id!=child.id
    # A network retry still resolves the original child if another request has
    # meanwhile resumed the source execution.
    row.state='RUNNING'; await test_session.commit()
    assert (await service.RestartExecution(request,context())).execution_id==child.id
    assert len(dispatcher.calls)==3


@pytest.mark.asyncio
async def test_restart_and_details_enforce_owner_and_terminal_state(test_session):
    service=OrchestratorServiceImpl(container_manager=Echo()); id=await original(service)
    for method,request in [(service.RestartExecution,pb.RestartExecutionRequest(execution_id=id,request_key='key')),
        (service.GetExecutionDetails,pb.GetExecutionStatusRequest(execution_id=id)),
        (service.GetNodeDetails,pb.NodeDetailsRequest(execution_id=id,node_id='echo')),
        (service.GetNodeLogs,pb.NodeLogsRequest(execution_id=id,node_id='echo',attempt_number=1))]:
        with pytest.raises(MockRpcError) as error: await method(request,context('other'))
        assert error.value.code()==grpc.StatusCode.NOT_FOUND
    with pytest.raises(MockRpcError) as error:
        await anext(service.DownloadNodeLog(pb.NodeLogRequest(execution_id=id,node_id='echo',attempt_number=1),context('other')))
    assert error.value.code()==grpc.StatusCode.NOT_FOUND
    row=await test_session.get(Execution,id); row.state='PAUSED'; await test_session.commit()
    with pytest.raises(MockRpcError) as error:
        await service.RestartExecution(pb.RestartExecutionRequest(execution_id=id,request_key='key'),context())
    assert error.value.code()==grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.asyncio
async def test_attempt_logs_paginate_and_download_without_cross_attempt_mixing(test_session):
    service=OrchestratorServiceImpl(container_manager=Echo()); id=await original(service)
    details=await service.GetNodeDetails(pb.NodeDetailsRequest(execution_id=id,node_id='echo'),context())
    attempt=details.attempts[0]
    assert attempt.number==1 and attempt.log_bytes>0 and not attempt.logs_truncated
    first=await service.GetNodeLogs(pb.NodeLogsRequest(execution_id=id,node_id='echo',attempt_number=1,page_size=1),context())
    assert len(first.entries)==1 and first.has_more
    second=await service.GetNodeLogs(pb.NodeLogsRequest(execution_id=id,node_id='echo',attempt_number=1,after_sequence=first.next_sequence),context())
    assert len(second.entries)==1 and not second.has_more and second.entries[0].sequence>first.next_sequence
    frames=[frame async for frame in service.DownloadNodeLog(pb.NodeLogRequest(execution_id=id,node_id='echo',attempt_number=1),context())]
    assert frames[-1].is_last and [frame.sequence for frame in frames]==list(range(len(frames)))
    data=b''.join(frame.data for frame in frames)
    assert b'Node attempt started' in data and b'Node attempt completed' in data
    with pytest.raises(MockRpcError) as error:
        await service.GetNodeLogs(pb.NodeLogsRequest(execution_id=id,node_id='echo',attempt_number=2),context())
    assert error.value.code()==grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_log_budget_is_explicit_in_details_and_download(test_session):
    from src.engine.attempts import LOG_LIMIT,append_log
    service=OrchestratorServiceImpl(container_manager=Echo()); id=await original(service)
    attempt=await test_session.scalar(select(Attempt).where(Attempt.execution_id==id))
    attempt.log_bytes=LOG_LIMIT-10
    append_log(test_session,attempt,'worker','INFO','this record exceeds remaining budget')
    await test_session.commit()
    details=await service.GetNodeDetails(pb.NodeDetailsRequest(execution_id=id,node_id='echo'),context())
    assert details.attempts[0].logs_truncated
    chunks=[chunk async for chunk in service.DownloadNodeLog(pb.NodeLogRequest(execution_id=id,node_id='echo',attempt_number=1),context())]
    assert chunks[-1].truncated and b'[TRUNCATED' in b''.join(chunk.data for chunk in chunks)
