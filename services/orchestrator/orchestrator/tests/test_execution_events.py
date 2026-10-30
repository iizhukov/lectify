import asyncio

import grpc
import pytest

from generated.protos.server import index_pb2 as pb
from generated.testing.context import MockRpcError
from src.models import NodeEventModel, WorkflowExecutionModel
from src.service import OrchestratorServiceImpl


@pytest.mark.asyncio
async def test_another_replica_replays_all_pages_and_resumes_after_cursor(test_session, mock_context):
    execution = WorkflowExecutionModel(id='event-history',workflow_id='workflow',user_id='user_1',state='COMPLETED')
    test_session.add(execution)
    await test_session.flush()
    test_session.add_all([NodeEventModel(execution_id=execution.id,node_id='node',event_id=f'event-{index}',
        owner='worker',fence=1,kind='progress',payload={'percent':index%101,'message':str(index)},
        content_hash='a'*64) for index in range(105)])
    await test_session.commit()
    reader = OrchestratorServiceImpl()
    events = [event async for event in reader.StreamExecutionEvents(
        pb.StreamExecutionEventsRequest(execution_id=execution.id), mock_context)]
    durable = [event for event in events if event.sequence]
    assert len(durable) == 105
    assert [event.sequence for event in durable] == sorted(event.sequence for event in durable)
    assert events[-1].metadata['snapshot'] == 'true' and events[-1].metadata['state'] == 'COMPLETED'
    resumed = [event async for event in OrchestratorServiceImpl().StreamExecutionEvents(
        pb.StreamExecutionEventsRequest(execution_id=execution.id,after_sequence=durable[99].sequence), mock_context)]
    assert [event.sequence for event in resumed if event.sequence] == [event.sequence for event in durable[100:]]


@pytest.mark.asyncio
async def test_terminal_state_closes_an_already_open_subscription(test_session, mock_context):
    execution = WorkflowExecutionModel(id='live-events',workflow_id='workflow',user_id='user_1',state='RUNNING')
    test_session.add(execution)
    await test_session.commit()
    stream = OrchestratorServiceImpl().StreamExecutionEvents(
        pb.StreamExecutionEventsRequest(execution_id=execution.id), mock_context)
    initial = await asyncio.wait_for(anext(stream), 1)
    assert initial.metadata['state'] == 'RUNNING'
    test_session.add(NodeEventModel(execution_id=execution.id,node_id='node',event_id='last-report',
        owner='worker',fence=1,kind='progress',payload={'percent':99,'message':'last before cancel'},
        content_hash='b'*64))
    execution.state = 'CANCELLED'
    await test_session.commit()
    report = await asyncio.wait_for(anext(stream), 1)
    assert report.sequence > 0 and report.message == 'last before cancel'
    final = await asyncio.wait_for(anext(stream), 1)
    assert final.metadata['state'] == 'CANCELLED'
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_negative_event_cursor_is_rejected(test_session, mock_context):
    with pytest.raises(MockRpcError) as error:
        await anext(OrchestratorServiceImpl().StreamExecutionEvents(
            pb.StreamExecutionEventsRequest(execution_id='missing',after_sequence=-1), mock_context))
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
