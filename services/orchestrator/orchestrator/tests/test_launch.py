import pytest
from sqlalchemy import select, func

from src.engine.dispatch import claim
from src.engine.launch import prepare_launch, begin_launch, record_container
from src.models import ContainerAttemptModel, WorkflowDispatchModel, WorkflowExecutionModel, WorkflowNodeExecutionModel


@pytest.mark.asyncio
async def test_worker_placement_survives_inventory_change_and_refuses_silent_migration(test_session):
    from generated.docker_workers import DockerWorkers
    from src.engine.launch import prepare_worker_launch
    test_session.add(WorkflowExecutionModel(id='placement',workflow_id='workflow',state='RUNNING'))
    await test_session.flush()
    test_session.add_all([WorkflowDispatchModel(execution_id='placement'),
        WorkflowNodeExecutionModel(execution_id='placement',node_id='node',plugin_id='plugin')])
    await test_session.commit()
    fence = await claim(test_session,'placement','owner')
    await test_session.commit()
    sandboxes = {'daemon-a':object(),'daemon-b':object()}
    scope = dict(execution_id='placement',node_id='node',owner='owner',fence=fence,
        role='plugin',image='sha256:'+'a'*64)
    first = await prepare_worker_launch(test_session,DockerWorkers(sandboxes),**scope)
    await test_session.commit()
    expanded = DockerWorkers({**sandboxes,'daemon-c':object()})
    assert await prepare_worker_launch(test_session,expanded,**scope) == first
    await test_session.commit()
    missing = DockerWorkers({key:value for key,value in sandboxes.items() if key != first[1]})
    with pytest.raises(RuntimeError,match='unavailable'):
        await prepare_worker_launch(test_session,missing,**scope)
    await test_session.rollback()
    row = await test_session.get(ContainerAttemptModel,first[0])
    assert row.daemon_id == first[1] and row.state == 'PREPARED'


@pytest.mark.asyncio
@pytest.mark.parametrize('daemon_failure', [False, True])
async def test_cleanup_preserves_current_assignment_and_retries_daemon_errors(test_session, daemon_failure):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.engine.launch import cleanup_created_containers
    test_session.add(WorkflowExecutionModel(id='cleanup', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id='cleanup', state='LEASED', fence=2))
    test_session.add_all([ContainerAttemptModel(id=key*32, execution_id='cleanup', node_id='node',
        fence=fence, role='plugin', image='image', daemon_id='daemon-a', state='CREATED', container_id=key*64)
        for key, fence in (('a',1),('b',2))])
    test_session.add(ContainerAttemptModel(id='c'*32, execution_id='cleanup', node_id='foreign',
        fence=1, role='plugin', image='image', daemon_id='daemon-b', state='CREATED', container_id='c'*64))
    await test_session.commit()
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    calls = []
    class Sandbox:
        async def daemon_identity(self):
            return 'daemon-a'
        async def reconcile(self, **scope):
            calls.append(scope)
            if daemon_failure:
                raise TimeoutError('unavailable')
            return False  # Successful Docker list establishes already absent.
    assert await cleanup_created_containers(factory, Sandbox()) == (0 if daemon_failure else 1)
    assert len(calls) == 1 and calls[0]['attempt_id'] == 'a'*32
    async with factory() as session:
        assert (await session.get(ContainerAttemptModel, 'a'*32)).state == ('CREATED' if daemon_failure else 'CLEANED')
        assert (await session.get(ContainerAttemptModel, 'b'*32)).state == 'CREATED'
        assert (await session.get(ContainerAttemptModel, 'c'*32)).state == 'CREATED'


@pytest.mark.asyncio
async def test_launch_intent_survives_retry_and_rejects_stale_owner(test_session):
    test_session.add(WorkflowExecutionModel(id='launch', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add_all([WorkflowDispatchModel(execution_id='launch'),
        WorkflowNodeExecutionModel(execution_id='launch', node_id='node', plugin_id='plugin')])
    await test_session.commit()
    fence = await claim(test_session, 'launch', 'worker-a', 100, 10)
    await test_session.commit()
    arguments = dict(execution_id='launch', node_id='node', owner='worker-a', fence=fence,
        role='plugin', image='registry/plugin@sha256:'+'a'*64, daemon_id='daemon-a', now=101)
    first = await prepare_launch(test_session, **arguments)
    await test_session.commit()
    assert len(first) == 32
    assert await prepare_launch(test_session, **arguments) == first
    await test_session.commit()
    assert await test_session.scalar(select(func.count()).select_from(ContainerAttemptModel)) == 1
    with pytest.raises(ValueError, match='immutable'):
        await prepare_launch(test_session, **{**arguments, 'image':'registry/plugin@sha256:'+'b'*64})
    await test_session.rollback()
    agent = await prepare_launch(test_session, **{**arguments, 'role':'agent'})
    await test_session.commit()
    assert agent != first
    launch_args = dict(attempt_id=first, execution_id='launch', owner='worker-a', fence=fence, now=102)
    assert await begin_launch(test_session, **launch_args)
    await test_session.commit()
    assert not await begin_launch(test_session, **launch_args)
    await test_session.commit()
    assert await record_container(test_session, **launch_args, container_id='d'*64)
    await test_session.commit()
    assert not await record_container(test_session, **launch_args, container_id='e'*64)
    await test_session.commit()
    new_fence = await claim(test_session, 'launch', 'worker-b', 110, 10)
    await test_session.commit()
    assert await prepare_launch(test_session, **{**arguments, 'now':111}) is None
    await test_session.rollback()
    assert not await begin_launch(test_session, **{**launch_args, 'attempt_id':agent, 'now':111})
    await test_session.rollback()
    replacement = await prepare_launch(test_session, **{**arguments, 'owner':'worker-b', 'fence':new_fence, 'now':111})
    await test_session.commit()
    assert replacement != first
    execution = await test_session.get(WorkflowExecutionModel, 'launch')
    execution.state = 'CANCELLED'
    await test_session.commit()
    assert not await begin_launch(test_session, attempt_id=replacement, execution_id='launch',
        owner='worker-b', fence=new_fence, now=112)
    await test_session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_before_start', [False, True])
async def test_durable_intent_and_identity_are_committed_before_external_actions(test_session, monkeypatch, cancel_before_start):
    from contextlib import asynccontextmanager
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.engine.launch import launch_container, launch_on_worker
    from generated.docker_workers import DockerWorkers
    test_session.add(WorkflowExecutionModel(id='ordered', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add_all([WorkflowDispatchModel(execution_id='ordered'),
        WorkflowNodeExecutionModel(execution_id='ordered', node_id='node', plugin_id='plugin')])
    await test_session.commit()
    fence = await claim(test_session, 'ordered', 'worker')
    await test_session.commit()
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    operations = []
    class Sandbox:
        async def daemon_identity(self):
            return 'daemon-a'
        @asynccontextmanager
        async def allocated(self, **assignment):
            async with factory() as session:
                row = await session.get(ContainerAttemptModel, assignment['attempt_id'])
                assert row.state == 'CREATING' and row.container_id is None
            operations.append('create')
            assert assignment['network_aliases'] == ('runtime-test',)
            assert assignment['image'] == 'registry/plugin@sha256:'+'a'*64
            if not cancel_before_start:
                assert assignment['environment'] == {'EXECUTION_ID':'ordered','NODE_ID':'node'}
            try:
                yield 'a'*64
            finally:
                operations.append('remove')
        async def start(self, identity):
            async with factory() as session:
                row = await session.scalar(select(ContainerAttemptModel).where(
                    ContainerAttemptModel.execution_id == 'ordered'))
                assert row.state == 'CREATED' and row.container_id == identity
            operations.append('start')
    if cancel_before_start:
        import src.engine.launch as launch_module
        from sqlalchemy import update
        record = launch_module.record_container
        async def cancel_after_record(session, **fields):
            accepted = await record(session, **fields)
            await session.commit()
            async with factory() as other:
                await other.execute(update(WorkflowExecutionModel).where(
                    WorkflowExecutionModel.id == 'ordered').values(state='CANCELLED'))
                await other.commit()
            return accepted
        monkeypatch.setattr(launch_module, 'record_container', cancel_after_record)
        with pytest.raises(RuntimeError, match='lost before start'):
            async with launch_container(factory, Sandbox(), execution_id='ordered', node_id='node',
                    owner='worker', fence=fence, role='plugin', image='registry/plugin@sha256:'+'a'*64,
                    environment={},network='internal',network_aliases=('runtime-test',)):
                pytest.fail('Cancelled container must not execute')
        assert operations == ['create','remove']
        return
    from src.engine.assignments import runtime_assignments
    @asynccontextmanager
    async def grants(**fields):
        async with factory() as session:
            row = await session.get(ContainerAttemptModel,fields['placement']['attempt_id'])
            assert row.state == 'PREPARED' and row.daemon_id == 'daemon-a'
        try:
            yield {'environment':{'EXECUTION_ID':'spoof','NODE_ID':'spoof'},
                'network':'internal','network_aliases':('runtime-test',),
                'runtime':{'endpoint':'runtime','token':'runtime-token','outputs':[],
                    'control':{'endpoint':'agent','token':'control-token','command_id':'spoof'}}}
        finally: operations.append('grants-cleanup')
    assignments = runtime_assignments(factory,DockerWorkers({'daemon-a':Sandbox()}),
        {('plugin','0.1.0'):'registry/plugin@sha256:'+'a'*64},grants)
    async with assignments(execution_id='ordered',node={'id':'node','plugin_id':'plugin',
            'parameters':{'image':'untrusted:latest'}},ownership=('worker',fence),initial_inputs={}) as runtime:
        assert len(runtime['control']['command_id']) == 32
        operations.append('execute')
    assert operations == ['create','start','execute','remove','grants-cleanup']
    async with factory() as session:
        assert await session.scalar(select(ContainerAttemptModel.state).where(
            ContainerAttemptModel.execution_id == 'ordered')) == 'CLEANED'
