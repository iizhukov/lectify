import json
from types import SimpleNamespace

import grpc
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models import NodeEventModel, WorkflowDispatchModel, WorkflowExecutionModel, WorkflowNodeExecutionModel
from src.node_events import report_node_event
from src.engine.dispatch import issue_report_capability


@pytest.mark.asyncio
@pytest.mark.parametrize('manual_rotation',[False,True])
async def test_expired_encrypted_report_capability_is_rejected_before_purge(test_session,manual_rotation):
    from cryptography.fernet import Fernet
    from generated.credential_cipher import CredentialCipher
    from src.engine.credentials import ExecutionCredentials
    from src.models import ExecutionCredentialModel
    store = ExecutionCredentials(CredentialCipher(Fernet.generate_key(),clock=lambda:0))
    test_session.add(WorkflowExecutionModel(id='expired-report',workflow_id='workflow',user_id='user',state='RUNNING'))
    await test_session.flush()
    test_session.add_all([WorkflowDispatchModel(execution_id='expired-report',state='LEASED',owner='worker',
        fence=1,lease_expires_at=9999999999),
        WorkflowNodeExecutionModel(execution_id='expired-report',node_id='node',plugin_id='plugin',state='PROCESSING'),
        store.prepare('expired-report','user','la_test',1)])
    await test_session.commit()
    token = await store.report_capability(test_session,execution_id='expired-report',owner_id='user',ownership=('worker',1))
    if manual_rotation:
        token = await issue_report_capability(test_session,'expired-report','worker',1)
    await test_session.commit()
    factory = async_sessionmaker(test_session.bind,expire_on_commit=False)
    request = SimpleNamespace(execution_id='expired-report',node_id='node',owner='worker',fence=1,
        event_id='expired',kind='progress',payload_json=json.dumps({'percent':50,'message':'half'}),report_token=token)
    with pytest.raises(Rejected) as error:
        await report_node_event(factory,request,Context())
    assert error.value.args[0] == grpc.StatusCode.UNAUTHENTICATED
    assert await test_session.get(ExecutionCredentialModel,'expired-report') is not None
    dispatch = await test_session.get(WorkflowDispatchModel,'expired-report')
    assert (dispatch.report_token_ciphertext is None) == manual_rotation
    assert dispatch.report_token_hash
    assert await test_session.scalar(select(func.count()).select_from(NodeEventModel)) == 0


class Rejected(Exception):
    pass


class Context:
    async def abort(self, code, details):
        raise Rejected(code, details)


@pytest.mark.asyncio
async def test_reports_are_durable_idempotent_and_fenced(test_session):
    test_session.add(WorkflowExecutionModel(id='execution', workflow_id='workflow', state='RUNNING'))
    await test_session.flush()
    test_session.add(WorkflowDispatchModel(execution_id='execution', state='LEASED', owner='worker',
        fence=1, lease_expires_at=9999999999))
    test_session.add(WorkflowNodeExecutionModel(execution_id='execution', node_id='node',
        plugin_id='plugin', state='PROCESSING'))
    await test_session.commit()
    token = await issue_report_capability(test_session, 'execution', 'worker', 1)
    await test_session.commit()
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    request = SimpleNamespace(execution_id='execution', node_id='node', owner='worker', fence=1,
        event_id='event', kind='progress', payload_json=json.dumps({'percent':50,'message':'half'}),
        report_token=token)
    first = await report_node_event(factory, request, Context())
    repeated = await report_node_event(factory, request, Context())
    assert first.accepted and repeated.sequence == first.sequence
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(NodeEventModel)) == 1
        node = await session.scalar(select(WorkflowNodeExecutionModel))
        assert node.progress_percent == 50
    request.payload_json = json.dumps({'percent':60,'message':'different'})
    with pytest.raises(Rejected) as error:
        await report_node_event(factory, request, Context())
    assert error.value.args[0] == grpc.StatusCode.ALREADY_EXISTS
    request.event_id = 'new-event'
    request.report_token = 'b' * 48
    with pytest.raises(Rejected) as error:
        await report_node_event(factory, request, Context())
    assert error.value.args[0] == grpc.StatusCode.UNAUTHENTICATED
    request.report_token = token
    request.fence = 2
    with pytest.raises(Rejected) as error:
        await report_node_event(factory, request, Context())
    assert error.value.args[0] == grpc.StatusCode.FAILED_PRECONDITION
    request.fence = 1
    request.event_id = 'regressive-progress'
    request.payload_json = json.dumps({'percent':10,'message':'late progress'})
    await report_node_event(factory, request, Context())
    async with factory() as session:
        node = await session.scalar(select(WorkflowNodeExecutionModel))
        assert node.progress_percent == 50
        execution = await session.get(WorkflowExecutionModel, 'execution')
        execution.state = 'CANCELLED'
        await session.commit()
    request.event_id = 'after-cancellation'
    with pytest.raises(Rejected) as error:
        await report_node_event(factory, request, Context())
    assert error.value.args[0] == grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.parametrize('payload', [
    '{"percent":1,"percent":2,"message":"duplicate"}',
    '{"percent":true,"message":"boolean"}',
    '{"percent":101,"message":"out of range"}',
    '{"percent":NaN,"message":"non-finite"}',
])
def test_progress_rejects_ambiguous_or_invalid_payload(payload):
    from src.node_events import _payload
    with pytest.raises(ValueError):
        _payload('progress', payload)


def test_node_event_migration_roundtrip():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migrations = Path(__file__).parents[1] / 'migrations/versions'
    loaded = []
    for filename in ('0001_orchestrator.py', '0002_node_events.py', '0003_container_attempts.py'):
        spec = importlib.util.spec_from_file_location(filename[:-3], migrations / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.append(module)
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                for migration in loaded:
                    migration.upgrade()
                assert 'workflow_node_events' in inspect(connection).get_table_names()
                assert 'workflow_container_attempts' in inspect(connection).get_table_names()
                columns = {column['name'] for column in inspect(connection).get_columns('workflow_dispatch')}
                assert {'report_token_hash', 'report_token_fence'} <= columns
                for migration in reversed(loaded):
                    migration.downgrade()
                assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
