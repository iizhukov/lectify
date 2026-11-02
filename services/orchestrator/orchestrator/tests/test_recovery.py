import asyncio
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock
import grpc
import pytest
from sqlalchemy import select,update,func
from generated.db.connection import get_session_factory
from generated.protos.server import index_pb2 as pb
from generated.stream_router import StreamChunkData as Frame
from generated.testing.context import MockServicerContext,MockRpcError
from src.models import WorkflowExecutionModel as Execution,WorkflowNodeExecutionModel as Node,WorkflowDispatchModel as Dispatch,StreamCheckpointFrameModel as Checkpoint
from src.service import OrchestratorServiceImpl

NODES=[{'id':'source','plugin_id':'source'},{'id':'sink','plugin_id':'sink'}]
EDGES=[dict(from_node_id='source',from_output='data',to_node_id='sink',to_input='data')]


def context(user='owner'):
    value=MockServicerContext(); value.lectify_principal=SimpleNamespace(user_id=user,is_admin=False)
    return value


async def saved_execution(session,id='recover'):
    row=Execution(id=id,workflow_id='workflow',user_id='owner',state='RUNNING',graph_json={'nodes':NODES,'edges':EDGES})
    session.add(row); await session.flush()
    session.add(Dispatch(execution_id=id))
    session.add_all([Node(execution_id=id,node_id=node['id'],plugin_id=node['plugin_id']) for node in NODES])
    await session.commit()
    return row


async def wait_source_checkpoint(execution_id):
    async with asyncio.timeout(3):
        while True:
            async with get_session_factory()() as session:
                ready=await session.scalar(select(Node.checkpoint_ready).where(Node.execution_id==execution_id,Node.node_id=='source'))
            if ready: return
            await asyncio.sleep(.01)


async def settle(service):
    tasks=list(service._execution_tasks.values())
    await asyncio.wait_for(asyncio.gather(*tasks),4)


class BlockingDispatcher:
    supports_streaming=True
    def __init__(self):
        self.calls=Counter(); self.started=asyncio.Event(); self.release=asyncio.Event(); self.received=[]
    async def stream_node(self,*,execution_id,node,inputs,**kwargs):
        self.calls[node['id']]+=1
        if node['id']=='source':
            yield Frame('data',b'persisted-output')
            yield Frame('data',b'',sequence=1,is_last=True)
        else:
            frames=[frame async for frame in inputs]
            self.received.append(b''.join(frame.payload for frame in frames))
            await wait_source_checkpoint(execution_id)
            self.started.set()
            await self.release.wait()


@pytest.mark.asyncio
async def test_pause_resume_on_another_replica_replays_completed_source(test_session):
    row=await saved_execution(test_session)
    dispatcher=BlockingDispatcher(); first=OrchestratorServiceImpl(container_manager=dispatcher)
    await first.dispatch_pending(); await asyncio.wait_for(dispatcher.started.wait(),3)
    paused=await first.PauseExecution(pb.PauseExecutionRequest(execution_id=row.id),context())
    assert paused.state==pb.EXECUTION_STATE_PAUSED
    await test_session.refresh(row); assert row.state=='PAUSED'
    paused_nodes=list(await test_session.scalars(select(Node).where(Node.execution_id==row.id)))
    assert {node.node_id:node.state for node in paused_nodes}=={'source':'COMPLETED','sink':'PENDING'}
    assert next(node for node in paused_nodes if node.node_id=='sink').progress_message=='Исполнение приостановлено'
    dispatch=await test_session.get(Dispatch,row.id); await test_session.refresh(dispatch)
    assert dispatch.owner is None and dispatch.lease_expires_at==0 and dispatch.state=='PAUSED'
    assert not any(not task.done() for task in first._execution_tasks.values())
    assert (await first.PauseExecution(pb.PauseExecutionRequest(execution_id=row.id),context())).success
    dispatcher.release.set()
    second=OrchestratorServiceImpl(container_manager=dispatcher)
    assert (await second.ResumeExecution(pb.ResumeExecutionRequest(execution_id=row.id),context())).success
    await settle(second)
    await test_session.refresh(row); assert row.state=='COMPLETED'
    assert dispatcher.calls=={'source':1,'sink':2}
    assert dispatcher.received==[b'persisted-output',b'persisted-output']
    assert await test_session.scalar(select(func.count()).select_from(Checkpoint))==2


@pytest.mark.asyncio
async def test_owner_loss_replays_checkpoint_with_new_fence(test_session):
    row=await saved_execution(test_session)
    dispatcher=BlockingDispatcher(); first=OrchestratorServiceImpl(container_manager=dispatcher)
    await first.dispatch_pending(); await asyncio.wait_for(dispatcher.started.wait(),3)
    task=first._execution_tasks[row.id]; task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    await test_session.execute(update(Dispatch).where(Dispatch.execution_id==row.id).values(lease_expires_at=0))
    await test_session.commit()
    dispatcher.release.set(); second=OrchestratorServiceImpl(container_manager=dispatcher)
    assert await second.dispatch_pending()==1; await settle(second)
    await test_session.refresh(row); assert row.state=='COMPLETED'
    assert dispatcher.calls=={'source':1,'sink':2}
    from src.engine.checkpoints import StreamCheckpoints
    stale=StreamCheckpoints(get_session_factory(),row.id,(first.worker_id,1))
    with pytest.raises(RuntimeError,match='lease'): await stale.append('source',2,Frame('data',b'late'))
    assert await test_session.scalar(select(func.count()).select_from(Checkpoint))==2


@pytest.mark.asyncio
async def test_retry_failed_node_does_not_repeat_completed_source(test_session):
    row=await saved_execution(test_session)
    dispatcher=BlockingDispatcher()
    original=dispatcher.stream_node
    async def flaky(**kwargs):
        if kwargs['node']['id']=='sink' and not dispatcher.started.is_set():
            dispatcher.calls['sink']+=1
            async for _ in kwargs['inputs']: pass
            await wait_source_checkpoint(row.id)
            dispatcher.started.set()
            raise RuntimeError('permanent first attempt failure')
        async for frame in original(**kwargs): yield frame
    dispatcher.stream_node=flaky; service=OrchestratorServiceImpl(container_manager=dispatcher)
    await service.dispatch_pending(); await settle(service)
    await test_session.refresh(row); assert row.state=='FAILED'
    dispatcher.release.set()
    assert (await service.RetryNode(pb.RetryNodeRequest(execution_id=row.id,node_id='sink'),context())).success
    await settle(service)
    await test_session.refresh(row); assert row.state=='COMPLETED'
    assert dispatcher.calls=={'source':1,'sink':2}
    assert dispatcher.received==[b'persisted-output']
    details=await service.GetNodeDetails(pb.NodeDetailsRequest(execution_id=row.id,node_id='sink'),context())
    assert [(attempt.number,attempt.state) for attempt in details.attempts]==[(2,'COMPLETED'),(1,'FAILED')]
    first=await service.GetNodeLogs(pb.NodeLogsRequest(execution_id=row.id,node_id='sink',attempt_number=1),context())
    second=await service.GetNodeLogs(pb.NodeLogsRequest(execution_id=row.id,node_id='sink',attempt_number=2),context())
    assert any('attempt failed' in entry.message for entry in first.entries)
    assert not any('attempt completed' in entry.message for entry in first.entries)
    assert any('attempt completed' in entry.message for entry in second.entries)
    assert not any('attempt failed' in entry.message for entry in second.entries)


@pytest.mark.asyncio
async def test_running_resume_is_idempotent_and_does_not_cancel_task(test_session):
    row=await saved_execution(test_session)
    dispatcher=BlockingDispatcher(); service=OrchestratorServiceImpl(container_manager=dispatcher)
    await service.dispatch_pending(); await asyncio.wait_for(dispatcher.started.wait(),3)
    task=service._execution_tasks[row.id]
    await service.ResumeExecution(pb.ResumeExecutionRequest(execution_id=row.id),context())
    assert not task.done() and not task.cancelling()
    dispatcher.release.set(); await settle(service)


@pytest.mark.asyncio
async def test_lifecycle_hides_other_users_and_rejects_terminal_resume(test_session):
    row=await saved_execution(test_session)
    service=OrchestratorServiceImpl()
    for method,request in [(service.PauseExecution,pb.PauseExecutionRequest(execution_id=row.id)),
        (service.ResumeExecution,pb.ResumeExecutionRequest(execution_id=row.id)),
        (service.RetryNode,pb.RetryNodeRequest(execution_id=row.id,node_id='source'))]:
        with pytest.raises(MockRpcError) as error: await method(request,context('other'))
        assert error.value.code()==grpc.StatusCode.NOT_FOUND
    row.state='COMPLETED'; await test_session.commit()
    with pytest.raises(MockRpcError) as error: await service.ResumeExecution(pb.ResumeExecutionRequest(execution_id=row.id),context())
    assert error.value.code()==grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.asyncio
async def test_transient_node_has_two_automatic_retries_then_can_be_retried_manually(test_session,monkeypatch):
    import src.service as module
    monkeypatch.setattr(module,'flags',SimpleNamespace(auto_retry_failed_nodes=True))
    row=await saved_execution(test_session)
    dispatcher=BlockingDispatcher(); original=dispatcher.stream_node
    async def unavailable(**kwargs):
        if kwargs['node']['id']=='sink' and dispatcher.calls['sink']<3:
            dispatcher.calls['sink']+=1
            async for _ in kwargs['inputs']: pass
            await wait_source_checkpoint(row.id)
            raise grpc.aio.AioRpcError(grpc.StatusCode.UNAVAILABLE,(),(),'safe status')
        async for frame in original(**kwargs): yield frame
    dispatcher.stream_node=unavailable; dispatcher.release.set()
    service=OrchestratorServiceImpl(container_manager=dispatcher)
    for number in range(3):
        await service.dispatch_pending(); await settle(service)
        await test_session.refresh(row)
        if number<2:
            assert row.state=='RUNNING' and row.automatic_retries==number+1
            await test_session.execute(update(Dispatch).where(Dispatch.execution_id==row.id).values(lease_expires_at=0))
            await test_session.commit()
        else: assert row.state=='FAILED' and row.automatic_retries==2
    assert dispatcher.calls=={'source':1,'sink':3}
    await service.RetryNode(pb.RetryNodeRequest(execution_id=row.id,node_id='sink'),context()); await settle(service)
    await test_session.refresh(row); assert row.state=='COMPLETED'
    assert dispatcher.calls=={'source':1,'sink':4}


@pytest.mark.asyncio
async def test_retry_invalidates_completed_descendants_but_preserves_other_branch(test_session):
    row=await saved_execution(test_session)
    row.state='FAILED'
    for node in await test_session.scalars(select(Node)):
        node.state='COMPLETED'; node.checkpoint_ready=True; node.output_artifacts={'output':'old'}
        test_session.add(Checkpoint(execution_id=row.id,node_id=node.node_id,position=0,stream_name='data',
            sequence=0,payload=b'old',is_last=True))
    test_session.add(Node(execution_id=row.id,node_id='independent',plugin_id='sink',state='COMPLETED',
        checkpoint_ready=True,output_artifacts={'output':'keep'}))
    test_session.add(Checkpoint(execution_id=row.id,node_id='independent',position=0,stream_name='data',
        sequence=0,payload=b'keep',is_last=True))
    await test_session.commit()
    service=OrchestratorServiceImpl(); service.dispatch_pending=AsyncMock(return_value=0)
    await service.RetryNode(pb.RetryNodeRequest(execution_id=row.id,node_id='source'),context())
    await test_session.refresh(row); assert row.state=='RUNNING'
    rows=list(await test_session.scalars(select(Node).execution_options(populate_existing=True)))
    for node in rows:
        if node.node_id=='independent':
            assert node.state=='COMPLETED' and node.output_artifacts=={'output':'keep'} and node.checkpoint_ready
        else: assert node.state=='PENDING' and not node.output_artifacts and not node.checkpoint_ready
    assert list(await test_session.scalars(select(Checkpoint.node_id)))==['independent']
