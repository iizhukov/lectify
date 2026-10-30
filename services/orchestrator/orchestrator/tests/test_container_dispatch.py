import pytest

from src.engine.docker_runner import ContainerLifecycleManager
from src.service import OrchestratorServiceImpl


@pytest.mark.asyncio
async def test_unconfigured_container_dispatch_cannot_report_success():
    service = OrchestratorServiceImpl()
    assert service.container_manager.use_mock is False
    progress = []
    with pytest.raises(RuntimeError, match='dispatcher is not configured'):
        await service.container_manager.start_plugin_node('execution', 'node', 'plugin', {},
            on_progress=lambda *event: progress.append(event))
    assert progress == []


@pytest.mark.asyncio
async def test_simulation_requires_explicit_test_dependency():
    service = OrchestratorServiceImpl(container_manager=ContainerLifecycleManager(use_mock=True))
    result = await service.container_manager.start_plugin_node('execution', 'node', 'plugin', {})
    assert result['status'] == 'COMPLETED'


@pytest.mark.asyncio
async def test_pipeline_without_dispatcher_persists_failure(test_session):
    from sqlalchemy import select
    from src.models import WorkflowExecutionModel, WorkflowNodeExecutionModel
    execution = WorkflowExecutionModel(id='no-dispatcher', workflow_id='workflow', state='RUNNING')
    test_session.add(execution)
    await test_session.flush()
    test_session.add(WorkflowNodeExecutionModel(execution_id=execution.id, node_id='node', plugin_id='plugin'))
    test_session.add(WorkflowNodeExecutionModel(execution_id=execution.id, node_id='done', plugin_id='plugin',
        state='COMPLETED', progress_percent=100, output_artifacts={'result':{'file_id':'saved'}}))
    await test_session.commit()
    service = OrchestratorServiceImpl()
    await service._run_execution_pipeline(execution.id, [{'id':'node','plugin_id':'plugin'}], None, {})
    await test_session.refresh(execution)
    assert execution.state == 'FAILED'
    assert execution.total_progress != 100
    assert execution.error_message == 'Plugin container dispatcher is not configured'
    node = await test_session.scalar(select(WorkflowNodeExecutionModel).where(
        WorkflowNodeExecutionModel.execution_id == execution.id, WorkflowNodeExecutionModel.node_id == 'node'))
    assert node.state == 'FAILED'
    assert node.error_message == execution.error_message
    completed = await test_session.scalar(select(WorkflowNodeExecutionModel).where(
        WorkflowNodeExecutionModel.execution_id == execution.id, WorkflowNodeExecutionModel.node_id == 'done'))
    assert completed.state == 'COMPLETED'
    assert completed.output_artifacts == {'result':{'file_id':'saved'}}


@pytest.mark.asyncio
async def test_recovery_does_not_launch_completed_nodes(test_session):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.models import WorkflowExecutionModel, WorkflowNodeExecutionModel
    test_session.add(WorkflowExecutionModel(id='resume', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add_all([
        WorkflowNodeExecutionModel(execution_id='resume', node_id='done', plugin_id='plugin',
            state='COMPLETED', progress_percent=100, output_artifacts={'saved':'artifact'}),
        WorkflowNodeExecutionModel(execution_id='resume', node_id='pending', plugin_id='plugin'),
    ])
    await test_session.commit()
    manager = ContainerLifecycleManager()
    manager.start_plugin_node = AsyncMock(return_value={'artifacts':{}})
    service = OrchestratorServiceImpl(container_manager=manager)
    await service._run_execution_pipeline('resume', [
        {'id':'done','plugin_id':'plugin'}, {'id':'pending','plugin_id':'plugin'},
    ], None, {})
    manager.start_plugin_node.assert_awaited_once()
    assert manager.start_plugin_node.await_args.kwargs['node_id'] == 'pending'
    async with async_sessionmaker(test_session.bind)() as session:
        completed = await session.scalar(select(WorkflowNodeExecutionModel).where(
            WorkflowNodeExecutionModel.execution_id == 'resume', WorkflowNodeExecutionModel.node_id == 'done'))
        assert completed.output_artifacts == {'saved':'artifact'}
