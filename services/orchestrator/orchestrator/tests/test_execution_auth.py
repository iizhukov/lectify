from types import SimpleNamespace

import grpc
import pytest

from generated.testing.context import MockServicerContext, MockRpcError
from generated.protos.server import index_pb2 as pb
from src.models import WorkflowExecutionModel
from src.service import OrchestratorServiceImpl


def context(user='attacker', admin=False):
    value = MockServicerContext(metadata={'x-user-id':'victim'})
    value.lectify_principal = SimpleNamespace(user_id=user, is_admin=admin)
    return value


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


@pytest.mark.asyncio
async def test_unimplemented_lifecycle_does_not_return_fabricated_success(test_session):
    row = WorkflowExecutionModel(id='owned', workflow_id='workflow', user_id='victim', state='RUNNING')
    test_session.add(row)
    await test_session.commit()
    service = OrchestratorServiceImpl()
    for method, request in (
        (service.PauseExecution,pb.PauseExecutionRequest(execution_id=row.id)),
        (service.ResumeExecution,pb.ResumeExecutionRequest(execution_id=row.id)),
        (service.RetryNode,pb.RetryNodeRequest(execution_id=row.id,node_id='node')),
    ):
        with pytest.raises(MockRpcError) as error:
            await method(request, context('victim'))
        assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED
    await test_session.refresh(row)
    assert row.state == 'RUNNING'
