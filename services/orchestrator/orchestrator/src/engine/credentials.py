"""Persist only encrypted credentials, scoped to a live execution lease."""
import time
from sqlalchemy import delete,exists,select
from src.engine.dispatch import guard_execution_write
from src.models import ExecutionCredentialModel,WorkflowExecutionModel


class ExecutionCredentials:
    def __init__(self,cipher,*,clock=time.time):
        self._cipher,self._clock = cipher,clock

    def prepare(self,execution_id,owner_id,token,expires_at):
        return ExecutionCredentialModel(execution_id=execution_id,owner_id=owner_id,expires_at=expires_at,
            ciphertext=self._cipher.seal(execution_id=execution_id,owner_id=owner_id,token=token,expires_at=expires_at))

    async def load(self,session,*,execution_id,owner_id,ownership):
        if ownership is None or not await guard_execution_write(session,execution_id,ownership):
            raise PermissionError('Execution credential lease is not active')
        execution = await session.get(WorkflowExecutionModel,execution_id)
        row = await session.get(ExecutionCredentialModel,execution_id)
        if execution is None or execution.user_id != owner_id or row is None or row.owner_id != owner_id:
            raise PermissionError('Execution credential is unavailable')
        return self._cipher.open(row.ciphertext,execution_id=execution_id,owner_id=owner_id,expires_at=row.expires_at)

    async def purge(self,session):
        terminal = exists(select(WorkflowExecutionModel.id).where(
            WorkflowExecutionModel.id == ExecutionCredentialModel.execution_id,
            WorkflowExecutionModel.state.in_(('COMPLETED','FAILED','CANCELLED'))))
        await session.execute(delete(ExecutionCredentialModel).where(
            (ExecutionCredentialModel.expires_at <= int(self._clock())) | terminal))
