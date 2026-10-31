import asyncio
from types import SimpleNamespace
import pytest
import grpc
from cryptography.fernet import Fernet
from sqlalchemy import update
from generated.credential_cipher import CredentialCipher
from generated.testing.context import MockServicerContext,MockRpcError
from generated.protos.server import index_pb2 as pb
from src.engine.credentials import ExecutionCredentials
from src.models import ExecutionCredentialModel,WorkflowDispatchModel
from src.service import OrchestratorServiceImpl
from src.engine.dispatch import claim


def context(token='la_test'):
    value = MockServicerContext(metadata={'x-user-authorization':'Bearer '+token})
    value.lectify_principal = SimpleNamespace(user_id='user',is_admin=False,access_expires_at=1000)
    return value


class Runner:
    requires_credentials = True
    def __init__(self): self.started = asyncio.Event()
    async def start_plugin_node(self,**fields):
        self.started.set()
        await asyncio.Event().wait()
    async def stop_node(self,*args): pass


@pytest.mark.asyncio
async def test_encrypted_start_survives_replica_and_does_not_rotate_on_retry(test_session):
    now = [100]
    key = Fernet.generate_key()
    cipher = CredentialCipher(key,clock=lambda:now[0])
    store = ExecutionCredentials(cipher,clock=lambda:now[0])
    runner = Runner()
    service = OrchestratorServiceImpl(runner,credential_store=store)
    request = pb.StartExecutionRequest(execution_id='credential-execution',
        graph=pb.WorkflowGraph(nodes=[pb.WorkflowNode(id='node',plugin_id='plugin')]))
    await service.StartExecution(request,context())
    try:
        await asyncio.wait_for(runner.started.wait(),2)
        row = await test_session.get(ExecutionCredentialModel,request.execution_id)
        ciphertext = row.ciphertext
        assert b'la_test' not in ciphertext
        dispatch = await test_session.get(WorkflowDispatchModel,request.execution_id)
        ownership = (service.worker_id,dispatch.fence)
        replica = ExecutionCredentials(CredentialCipher(key,clock=lambda:now[0]))
        assert await replica.load(test_session,execution_id=request.execution_id,owner_id='user',ownership=ownership) == 'la_test'
        first_report = await store.report_capability(test_session,execution_id=request.execution_id,
            owner_id='user',ownership=ownership)
        await test_session.commit()
        assert await replica.report_capability(test_session,execution_id=request.execution_id,
            owner_id='user',ownership=ownership) == first_report
        await test_session.commit()
        await test_session.refresh(dispatch)
        report_ciphertext = dispatch.report_token_ciphertext
        assert first_report.encode() not in report_ciphertext
        for data,purpose,generation in ((ciphertext,'report',ownership[1]),
                (report_ciphertext,'user',0),(report_ciphertext,'report',ownership[1]+1)):
            with pytest.raises(PermissionError):
                cipher.open(data,execution_id=request.execution_id,owner_id='user',expires_at=1000,
                    purpose=purpose,generation=generation)
        await service.StartExecution(request,context('la_replacement'))
        await test_session.refresh(row)
        assert row.ciphertext == ciphertext
        for changes in ({'owner_id':'other'},{'execution_id':'other'},{'expires_at':2000},
                        {'ciphertext':ciphertext[:-1]+b'!'}):
            fields = dict(ciphertext=ciphertext,execution_id=request.execution_id,owner_id='user',expires_at=1000)
            fields.update(changes)
            with pytest.raises(PermissionError): cipher.open(**fields)
        await test_session.execute(update(WorkflowDispatchModel).where(
            WorkflowDispatchModel.execution_id == request.execution_id).values(lease_expires_at=0))
        await test_session.commit()
        new_fence = await claim(test_session,request.execution_id,'replacement')
        await test_session.commit()
        await test_session.refresh(dispatch)
        assert dispatch.report_token_ciphertext is None and dispatch.report_token_hash is None
        with pytest.raises(PermissionError):
            await store.report_capability(test_session,execution_id=request.execution_id,owner_id='user',ownership=ownership)
        await test_session.rollback()
        ownership = ('replacement',new_fence)
        assert await store.report_capability(test_session,execution_id=request.execution_id,
            owner_id='user',ownership=ownership) != first_report
        await test_session.commit()
        now[0] = 1000
        with pytest.raises(PermissionError,match='expired'):
            await store.load(test_session,execution_id=request.execution_id,owner_id='user',ownership=ownership)
        await test_session.rollback()
    finally:
        await service.CancelExecution(pb.CancelExecutionRequest(execution_id=request.execution_id),context())
        await asyncio.gather(*list(service._execution_tasks.values()),return_exceptions=True)
    await service.dispatch_pending()
    assert await test_session.get(ExecutionCredentialModel,request.execution_id) is None
    await test_session.refresh(dispatch)
    assert dispatch.report_token_ciphertext is None and dispatch.report_token_hash is None


@pytest.mark.asyncio
async def test_required_background_credentials_fail_closed_without_key(monkeypatch):
    monkeypatch.delenv('LECTIFY_EXECUTION_CREDENTIAL_KEY',raising=False)
    request = pb.StartExecutionRequest(graph=pb.WorkflowGraph(nodes=[pb.WorkflowNode(id='node',plugin_id='plugin')]))
    with pytest.raises(MockRpcError) as error:
        await OrchestratorServiceImpl(Runner()).StartExecution(request,context())
    assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
