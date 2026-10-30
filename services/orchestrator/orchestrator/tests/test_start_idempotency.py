import asyncio
from types import SimpleNamespace

import grpc
import pytest
from sqlalchemy import select, func

from generated.protos.server import index_pb2 as pb
from generated.testing.context import MockServicerContext, MockRpcError
from src.models import WorkflowExecutionModel, WorkflowNodeExecutionModel, WorkflowDispatchModel
from src.service import OrchestratorServiceImpl


class WaitingRunner:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
    async def start_plugin_node(self, **kwargs):
        self.calls += 1
        self.started.set()
        await asyncio.Event().wait()


def request():
    return pb.StartExecutionRequest(execution_id='stable-request',workflow_id='workflow',
        graph=pb.WorkflowGraph(nodes=[pb.WorkflowNode(id='node',plugin_id='plugin')]),
        initial_inputs={'file_id':'file'})


@pytest.mark.asyncio
async def test_concurrent_start_on_two_replicas_creates_one_execution(test_session, mock_context):
    runner = WaitingRunner()
    first, second = [OrchestratorServiceImpl(container_manager=runner) for _ in range(2)]
    responses = await asyncio.gather(first.StartExecution(request(), mock_context), second.StartExecution(request(), mock_context))
    try:
        await asyncio.wait_for(runner.started.wait(), 2)
        assert responses[0].execution_id == responses[1].execution_id == 'stable-request'
        assert responses[0].started_at == responses[1].started_at
        assert runner.calls == 1
        for model in (WorkflowExecutionModel, WorkflowDispatchModel, WorkflowNodeExecutionModel):
            assert await test_session.scalar(select(func.count()).select_from(model)) == 1
        await test_session.rollback()
    finally:
        for service in (first,second):
            await service.CancelExecution(pb.CancelExecutionRequest(execution_id='stable-request'), mock_context)
            await asyncio.gather(*list(service._execution_tasks.values()), return_exceptions=True)


@pytest.mark.asyncio
async def test_reused_id_rejects_changed_request_and_does_not_restart_terminal_execution(test_session, mock_context):
    runner = WaitingRunner()
    service = OrchestratorServiceImpl(container_manager=runner)
    initial = await service.StartExecution(request(), mock_context)
    await asyncio.wait_for(runner.started.wait(), 2)
    try:
        changed = request()
        changed.initial_inputs['file_id'] = 'another-file'
        with pytest.raises(MockRpcError) as error:
            await service.StartExecution(changed, mock_context)
        assert error.value.code() == grpc.StatusCode.ALREADY_EXISTS
        foreign = MockServicerContext()
        foreign.lectify_principal = SimpleNamespace(user_id='another-user',is_admin=False)
        with pytest.raises(MockRpcError) as error:
            await service.StartExecution(request(), foreign)
        assert error.value.code() == grpc.StatusCode.NOT_FOUND
    finally:
        await service.CancelExecution(pb.CancelExecutionRequest(execution_id='stable-request'), mock_context)
    repeated = await service.StartExecution(request(), mock_context)
    assert repeated.execution_id == initial.execution_id and repeated.state == pb.EXECUTION_STATE_CANCELLED
    assert runner.calls == 1 and not service._execution_tasks
