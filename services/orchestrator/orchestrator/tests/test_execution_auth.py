from types import SimpleNamespace

import grpc
import pytest

from generated.testing.context import MockServicerContext, MockRpcError
from generated.protos.server import index_pb2 as pb
from src.models import WorkflowExecutionModel, WorkflowNodeExecutionModel
from src.service import OrchestratorServiceImpl


def context(user='attacker', admin=False):
    value = MockServicerContext(metadata={'x-user-id':'victim'})
    value.lectify_principal = SimpleNamespace(user_id=user, is_admin=admin)
    return value


@pytest.mark.asyncio
async def test_execution_history_is_owner_scoped_and_artifacts_are_downloadable_ids(test_session):
    for identity, owner in (('a','alice'),('b','alice'),('private','bob')):
        test_session.add(WorkflowExecutionModel(id=identity,workflow_id='snapshot',user_id=owner,state='COMPLETED'))
    await test_session.flush()
    file_id = '12345678-1234-1234-1234-123456789abc'
    test_session.add(WorkflowNodeExecutionModel(execution_id='a',node_id='output',plugin_id='text_output',
        state='COMPLETED',output_artifacts={'result':{'file_id':file_id,'size_bytes':10}}))
    await test_session.commit()
    service = OrchestratorServiceImpl()
    first = await service.ListExecutions(pb.ListExecutionsRequest(page_size=1),context('alice'))
    second = await service.ListExecutions(pb.ListExecutionsRequest(page_size=1,offset=1),context('alice'))
    assert first.has_more and not second.has_more
    assert {first.executions[0].execution_id,second.executions[0].execution_id} == {'a','b'}
    status = await service.GetExecutionStatus(pb.GetExecutionStatusRequest(execution_id='a'),context('alice'))
    assert status.nodes[0].output_artifacts['result'] == file_id
    with pytest.raises(MockRpcError):
        await service.ListExecutions(pb.ListExecutionsRequest(page_size=101),context('alice'))


@pytest.mark.asyncio
async def test_start_requires_verified_principal_and_rejects_owner_spoof():
    service = OrchestratorServiceImpl()
    with pytest.raises(MockRpcError) as error:
        await service.StartExecution(pb.StartExecutionRequest(user_id='victim'), MockServicerContext())
    assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
    with pytest.raises(MockRpcError) as error:
        await service.StartExecution(pb.StartExecutionRequest(user_id='victim'), context())
    assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_private_execution_cannot_be_read_cancelled_or_subscribed_by_another_user(test_session):
    row = WorkflowExecutionModel(id='private-execution', workflow_id='workflow', user_id='victim', state='RUNNING')
    test_session.add(row)
    await test_session.commit()
    service = OrchestratorServiceImpl()
    for method, request in (
        (service.GetExecutionStatus, pb.GetExecutionStatusRequest(execution_id=row.id)),
        (service.CancelExecution, pb.CancelExecutionRequest(execution_id=row.id)),
    ):
        with pytest.raises(MockRpcError) as error:
            await method(request, context())
        assert error.value.code() == grpc.StatusCode.NOT_FOUND
    with pytest.raises(MockRpcError) as error:
        await anext(service.StreamExecutionEvents(pb.StreamExecutionEventsRequest(execution_id=row.id), context()))
    assert error.value.code() == grpc.StatusCode.NOT_FOUND
    assert not service._event_subscribers
    await test_session.refresh(row)
    assert row.state == 'RUNNING'
    response = await service.GetExecutionStatus(pb.GetExecutionStatusRequest(execution_id=row.id), context('victim'))
    assert response.execution_id == row.id


@pytest.mark.asyncio
async def test_plugin_registration_requires_admin():
    with pytest.raises(MockRpcError) as error:
        await OrchestratorServiceImpl().RegisterPluginManifest(pb.RegisterPluginManifestRequest(), context())
    assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED
