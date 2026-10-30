import pytest

from src.engine.dispatch import claim, renew
from src.models import WorkflowDispatchModel, WorkflowExecutionModel


@pytest.mark.asyncio
async def test_expired_claim_changes_fence_and_rejects_stale_worker(test_session):
    test_session.add(WorkflowExecutionModel(id='leased', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id='leased'))
    await test_session.commit()
    first = await claim(test_session, 'leased', 'worker-a', 100, 10)
    await test_session.commit()
    assert first == 1
    assert await claim(test_session, 'leased', 'worker-b', 100, 10) is None
    await test_session.commit()
    second = await claim(test_session, 'leased', 'worker-b', 110, 10)
    await test_session.commit()
    assert second == 2
    assert not await renew(test_session, 'leased', 'worker-a', first, 111)
    assert await renew(test_session, 'leased', 'worker-b', second, 111)
    await test_session.commit()


@pytest.mark.asyncio
async def test_cancelled_execution_cannot_claim_or_renew(test_session):
    row = WorkflowExecutionModel(id='stopped-lease', workflow_id='workflow', state='RUNNING')
    test_session.add(row)
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id=row.id))
    await test_session.commit()
    fence = await claim(test_session, row.id, 'worker', 100)
    await test_session.commit()
    row.state = 'CANCELLED'
    await test_session.commit()
    assert not await renew(test_session, row.id, 'worker', fence, 101)
    assert await claim(test_session, row.id, 'other', 200) is None


def test_orchestrator_migration_roundtrip():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / 'migrations/versions/0001_orchestrator.py'
    spec = importlib.util.spec_from_file_location('orchestrator_initial_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert set(inspect(connection).get_table_names()) == {
                'workflow_executions', 'workflow_node_executions', 'plugin_registry', 'workflow_dispatch',
            }
            migration.downgrade()
            assert inspect(connection).get_table_names() == []
    engine.dispose()


@pytest.mark.asyncio
async def test_two_service_instances_only_one_starts_claimed_pipeline(test_session):
    import asyncio
    from src.service import OrchestratorServiceImpl
    test_session.add(WorkflowExecutionModel(id='two-workers', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id='two-workers'))
    await test_session.commit()
    first, second = OrchestratorServiceImpl(), OrchestratorServiceImpl()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def pipeline(*args):
        calls.append(args[0])
        entered.set()
        await release.wait()
    first._run_execution_pipeline = pipeline
    second._run_execution_pipeline = pipeline
    task = asyncio.create_task(first._run_owned_pipeline('two-workers', [], None, {}))
    await asyncio.wait_for(entered.wait(), 2)
    await second._run_owned_pipeline('two-workers', [], None, {})
    assert calls == ['two-workers']
    release.set()
    await asyncio.wait_for(task, 2)
