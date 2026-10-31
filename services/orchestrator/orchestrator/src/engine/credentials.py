"""Persist only encrypted credentials, scoped to a live execution lease."""
import time
import hashlib
import hmac
from sqlalchemy import delete,exists,select,update
from src.engine.dispatch import guard_execution_write,issue_report_capability
from src.models import ExecutionCredentialModel,WorkflowExecutionModel,WorkflowDispatchModel


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
        token = self._cipher.open(row.ciphertext,execution_id=execution_id,owner_id=owner_id,expires_at=row.expires_at)
        execution.credentials_required = True
        return token

    async def purge(self,session):
        terminal = exists(select(WorkflowExecutionModel.id).where(
            WorkflowExecutionModel.id == ExecutionCredentialModel.execution_id,
            WorkflowExecutionModel.state.in_(('COMPLETED','FAILED','CANCELLED'))))
        await session.execute(delete(ExecutionCredentialModel).where(
            (ExecutionCredentialModel.expires_at <= int(self._clock())) | terminal))
        live = exists(select(ExecutionCredentialModel.execution_id).where(
            ExecutionCredentialModel.execution_id == WorkflowDispatchModel.execution_id))
        await session.execute(update(WorkflowDispatchModel).where(
            WorkflowDispatchModel.report_token_ciphertext.is_not(None),~live,
        ).values(report_token_ciphertext=None,report_token_hash=None,report_token_fence=None))

    async def report_capability(self,session,*,execution_id,owner_id,ownership):
        await self.load(session,execution_id=execution_id,owner_id=owner_id,ownership=ownership)
        credential = await session.get(ExecutionCredentialModel,execution_id)
        dispatch = await session.scalar(select(WorkflowDispatchModel).where(
            WorkflowDispatchModel.execution_id == execution_id).execution_options(populate_existing=True))
        binding = dict(execution_id=execution_id,owner_id=owner_id,expires_at=credential.expires_at,
            purpose='report',generation=ownership[1])
        if dispatch.report_token_ciphertext is not None:
            token = self._cipher.open(dispatch.report_token_ciphertext,**binding)
            digest = hashlib.sha256(token.encode('ascii')).hexdigest()
            if (dispatch.report_token_fence != ownership[1]
                    or not isinstance(dispatch.report_token_hash,str) or not dispatch.report_token_hash.isascii()
                    or not hmac.compare_digest(
                        digest,dispatch.report_token_hash)):
                raise PermissionError('Reporting capability state does not match execution lease')
            return token
        token = await issue_report_capability(session,execution_id,ownership[0],ownership[1])
        if token is None:
            raise PermissionError('Reporting capability lease is not active')
        dispatch.report_token_ciphertext = self._cipher.seal(token=token,**binding)
        return token
