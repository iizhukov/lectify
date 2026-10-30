import pytest

from src.engine.dispatch import claim, renew
from src.models import WorkflowDispatchModel, WorkflowExecutionModel


@pytest.mark.asyncio
async def test_reporting_capability_requires_current_claim_and_rotates(test_session):
    import hashlib
    from src.engine.dispatch import issue_report_capability
    test_session.add(WorkflowExecutionModel(id='capability', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id='capability'))
    await test_session.commit()
    first = await claim(test_session, 'capability', 'worker-a', 100, 10)
    await test_session.commit()
    token = await issue_report_capability(test_session, 'capability', 'worker-a', first, 101)
    await test_session.commit()
    assert len(token) >= 32
    await test_session.refresh(row := await test_session.get(WorkflowDispatchModel, 'capability'))
    assert row.report_token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.report_token_fence == first
    rotated = await issue_report_capability(test_session, 'capability', 'worker-a', first, 102)
    await test_session.commit()
    assert rotated != token
    second = await claim(test_session, 'capability', 'worker-b', 110, 10)
    await test_session.commit()
    await test_session.refresh(row)
    assert row.report_token_hash is None and row.report_token_fence is None
    assert await issue_report_capability(test_session, 'capability', 'worker-a', first, 111) is None
    await test_session.rollback()
    assert await issue_report_capability(test_session, 'capability', 'worker-b', second, 111)
    await test_session.commit()
    assert await issue_report_capability(test_session, 'capability', 'worker-b', second, 120) is None
    await test_session.rollback()


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
    assert not first._active_routers and not second._active_routers


@pytest.mark.asyncio
async def test_stale_worker_cannot_lock_execution_for_result_write(test_session):
    from src.engine.dispatch import guard_execution_write
    row = WorkflowExecutionModel(id='fenced-write', workflow_id='workflow', state='RUNNING')
    test_session.add(row)
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id=row.id))
    await test_session.commit()
    first = await claim(test_session, row.id, 'old', 100, 10)
    await test_session.commit()
    second = await claim(test_session, row.id, 'new', 110, 10)
    await test_session.commit()
    assert not await guard_execution_write(test_session, row.id, ('old', first), 111)
    await test_session.rollback()
    assert await guard_execution_write(test_session, 'fenced-write', ('new', second), 111)
    await test_session.commit()
    assert not await guard_execution_write(test_session, 'fenced-write', ('new', second), 120)


@pytest.mark.asyncio
async def test_default_lease_clock_is_database_time(test_session):
    from sqlalchemy import select
    from src.engine.dispatch import guard_execution_write
    test_session.add(WorkflowExecutionModel(id='db-clock', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id='db-clock'))
    await test_session.commit()
    fence = await claim(test_session, 'db-clock', 'worker')
    await test_session.commit()
    assert fence == 1
    expiry = await test_session.scalar(select(WorkflowDispatchModel.lease_expires_at).where(
        WorkflowDispatchModel.execution_id == 'db-clock',
    ))
    assert expiry > 1000000000
    assert await renew(test_session, 'db-clock', 'worker', fence)
    await test_session.commit()
    assert await guard_execution_write(test_session, 'db-clock', ('worker', fence))
    await test_session.commit()


@pytest.mark.asyncio
async def test_new_service_recovers_persisted_unclaimed_execution(test_session):
    import asyncio
    from src.service import OrchestratorServiceImpl
    row = WorkflowExecutionModel(id='recover-pending', workflow_id='workflow', state='RUNNING',
        graph_json={'nodes': [{'id': 'source', 'plugin_id': 'input_streamer'}], 'edges': []}, initial_inputs={'file': 'id'})
    test_session.add(row)
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id=row.id))
    await test_session.commit()
    recovered = []
    service = OrchestratorServiceImpl()
    async def pipeline(execution_id, nodes, dag, inputs, ownership):
        recovered.append((execution_id, nodes[0]['id'], inputs, ownership))
    service._run_execution_pipeline = pipeline
    assert await service.dispatch_pending() == 1
    tasks = list(service._execution_tasks.values())
    await asyncio.wait_for(asyncio.gather(*tasks), 2)
    assert recovered[0][:3] == ('recover-pending', 'source', {'file': 'id'})
    assert recovered[0][3] == (service.worker_id, 1)
    assert await service.dispatch_pending() == 0


@pytest.mark.asyncio
async def test_new_owner_invalidates_previous_reporting_capability(test_session):
    from sqlalchemy import select
    row = WorkflowExecutionModel(id='rotate-report-capability', workflow_id='workflow', state='RUNNING')
    test_session.add(row)
    await test_session.flush()
    assignment = WorkflowDispatchModel(execution_id=row.id, state='LEASED', owner='old',
        fence=1, lease_expires_at=100, report_token_hash='old-hash', report_token_fence=1)
    test_session.add(assignment)
    await test_session.commit()
    assert await claim(test_session, row.id, 'new', 100) == 2
    await test_session.commit()
    await test_session.refresh(assignment)
    assert assignment.report_token_hash is None
    assert assignment.report_token_fence is None


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_graph', [None, [], {'nodes': [None]}, {'nodes': [{'id':'a'}], 'edges': 'invalid'}])
async def test_invalid_saved_graph_does_not_starve_healthy_execution(test_session, bad_graph):
    import asyncio
    from src.service import OrchestratorServiceImpl
    for execution_id, graph in (
        ('a-invalid', bad_graph),
        ('b-healthy', {'nodes':[{'id':'source','plugin_id':'input_streamer'}], 'edges':[]}),
    ):
        test_session.add(WorkflowExecutionModel(id=execution_id, workflow_id='workflow', state='RUNNING',
            graph_json=graph, initial_inputs={}))
        await test_session.flush()
        test_session.add(WorkflowDispatchModel(execution_id=execution_id))
    await test_session.commit()
    service = OrchestratorServiceImpl()
    recovered = []
    async def pipeline(execution_id, *args):
        recovered.append(execution_id)
    service._run_execution_pipeline = pipeline
    assert await service.dispatch_pending() == 1
    await asyncio.wait_for(asyncio.gather(*list(service._execution_tasks.values())), 2)
    assert recovered == ['b-healthy']
    await test_session.refresh(invalid := await test_session.get(WorkflowExecutionModel, 'a-invalid'))
    assert invalid.state == 'FAILED'
    assert invalid.error_message == 'Invalid persisted workflow'
