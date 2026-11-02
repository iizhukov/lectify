"""Persist lifecycle transitions and revoke the previous owner's authority atomically."""
from sqlalchemy import delete,select,update
from src.models import WorkflowExecutionModel as Execution,WorkflowDispatchModel as Dispatch
from src.models import WorkflowNodeExecutionModel as Node,StreamCheckpointFrameModel as Frame


async def locked_execution(session,execution_id):
    # Same lock order as lease guards and node reports.
    dispatch=await session.scalar(select(Dispatch).where(Dispatch.execution_id==execution_id).with_for_update())
    execution=await session.scalar(select(Execution).where(Execution.id==execution_id).with_for_update())
    if execution is None: raise LookupError('Execution not found')
    if dispatch is None: raise ValueError('Execution dispatch is unavailable')
    return execution,dispatch


def revoke(dispatch,state):
    dispatch.fence+=1
    dispatch.state=state
    dispatch.owner=None
    dispatch.lease_expires_at=0
    dispatch.report_token_hash=None
    dispatch.report_token_fence=None
    dispatch.report_token_ciphertext=None


async def reset_unfinished(session,execution_id,*,invalidated=(),reset_retries=False):
    nodes=list(await session.scalars(select(Node).where(Node.execution_id==execution_id)))
    reset=[]
    for node in nodes:
        if node.state!='COMPLETED' or node.node_id in invalidated:
            reset.append(node.node_id)
            node.state,node.progress_percent,node.progress_message='PENDING',0,''
            node.checkpoint_ready=False
            node.output_artifacts={}
            node.error_message=None
            if reset_retries: node.automatic_retries=0
            node.bytes_streamed_in=node.bytes_streamed_out=node.chunks_processed=node.execution_time_ms=0
        elif not node.checkpoint_ready:
            raise ValueError('Historical node has no durable checkpoint; start a new execution')
    await session.execute(delete(Frame).where(Frame.execution_id==execution_id,Frame.node_id.in_(reset)))
    return int(100*(len(nodes)-len(reset))/len(nodes)) if nodes else 0


def descendants(graph,node_id):
    ids={node['id'] for node in graph['nodes']}
    if node_id not in ids: raise LookupError('Execution node not found')
    result={node_id}
    for _ in range(len(ids)):
        expanded=result|{edge['to_node_id'] for edge in graph['edges'] if edge['from_node_id'] in result}
        if expanded==result: return result
        result=expanded
    return result
