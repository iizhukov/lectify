"""Attempt history is owned by the application, independent of Docker cleanup state."""
import hashlib
import json
import uuid
from sqlalchemy import select,update,func
from src.models import WorkflowNodeAttemptModel as Attempt,WorkflowNodeExecutionModel as Node,NodeEventModel,utc_now

LOG_LIMIT=1048576


def append_log(session,attempt,owner,level,message,fields=None):
    payload=dict(level=level,message=message,fields=fields or {})
    serialized=json.dumps(payload,ensure_ascii=False,sort_keys=True)
    size=len(serialized.encode())
    if attempt.log_bytes+size>LOG_LIMIT:
        attempt.logs_truncated=True
        return
    attempt.log_bytes+=size
    session.add(NodeEventModel(execution_id=attempt.execution_id,node_id=attempt.node_id,event_id=uuid.uuid4().hex,
        owner=owner or 'orchestrator',fence=attempt.fence,kind='log',payload=payload,
        content_hash=hashlib.sha256(serialized.encode()).hexdigest()))


async def begin(session,execution_id,node_id,ownership):
    # Caller holds the dispatch/execution lock.
    fence=ownership[1] if ownership is not None else 0
    active=list(await session.scalars(select(Attempt).where(Attempt.execution_id==execution_id,
        Attempt.node_id==node_id,Attempt.state=='PROCESSING')))
    for row in active:
        row.state,row.finished_at='INTERRUPTED',utc_now()
        append_log(session,row,ownership[0] if ownership else None,'WARNING','Attempt interrupted before completion')
    number=(await session.scalar(select(func.max(Attempt.number)).where(Attempt.execution_id==execution_id,Attempt.node_id==node_id)) or 0)+1
    attempt=Attempt(id=uuid.uuid4().hex,execution_id=execution_id,node_id=node_id,number=number,fence=fence,
        state='PROCESSING',log_bytes=0,logs_truncated=False)
    session.add(attempt)
    append_log(session,attempt,ownership[0] if ownership else None,'INFO','Node attempt started')
    return attempt.id


async def finish(session,execution_id,node_id,state,ownership,stats=None,error_type=None,logs_incomplete=False):
    fence=ownership[1] if ownership is not None else 0
    attempt=await session.scalar(select(Attempt).where(Attempt.execution_id==execution_id,Attempt.node_id==node_id,
        Attempt.fence==fence,Attempt.state=='PROCESSING'))
    if attempt is None: return
    attempt.state,attempt.finished_at=state,utc_now()
    attempt.error_message=error_type
    attempt.logs_truncated=attempt.logs_truncated or logs_incomplete or state=='INTERRUPTED'
    node=await session.scalar(select(Node).where(Node.execution_id==execution_id,Node.node_id==node_id))
    attempt.output_artifacts=dict(node.output_artifacts or {}) if node else {}
    if stats:
        attempt.bytes_streamed_in=stats['input']; attempt.bytes_streamed_out=stats['output']
        attempt.chunks_processed=stats['chunks']; attempt.execution_time_ms=stats['elapsed']
    append_log(session,attempt,ownership[0] if ownership else None,'INFO' if state=='COMPLETED' else 'ERROR',
        'Node attempt '+state.lower(),{'error_type':error_type} if error_type else {})


async def interrupt(session,execution_id,state,*,before_fence=None):
    rows=list(await session.scalars(select(Attempt).where(Attempt.execution_id==execution_id,Attempt.state=='PROCESSING',
        *([Attempt.fence<before_fence] if before_fence is not None else []))))
    for attempt in rows:
        attempt.state,attempt.finished_at=state,utc_now()
        attempt.logs_truncated=True
        node=await session.scalar(select(Node).where(Node.execution_id==execution_id,Node.node_id==attempt.node_id))
        if node is not None: attempt.output_artifacts=dict(node.output_artifacts or {})
        append_log(session,attempt,None,'WARNING','Node attempt '+state.lower())
