"""Owner-authorized execution introspection and bounded durable log replay."""
import json
import grpc
from sqlalchemy import select
from generated.protos.server import index_pb2 as pb
from src.execution_events import epoch
from src.models import WorkflowExecutionModel as Execution,WorkflowNodeExecutionModel as Node,WorkflowNodeAttemptModel as Attempt,ContainerAttemptModel as Container,NodeEventModel as Event
from generated.runtime_logs import sanitize,sanitize_fields,secret_values


def timestamp(value): return epoch(value) if value else 0


async def node_details(session,execution,node_id,context,size=20,offset=0):
    definition=next((node for node in execution.graph_json['nodes'] if node['id']==node_id),None)
    node=await session.scalar(select(Node).where(Node.execution_id==execution.id,Node.node_id==node_id))
    if definition is None or node is None: await context.abort(grpc.StatusCode.NOT_FOUND,'Execution node not found')
    attempts=list(await session.scalars(select(Attempt).where(Attempt.execution_id==execution.id,Attempt.node_id==node_id)
        .order_by(Attempt.number.desc()).offset(offset).limit(size+1)))
    values=[]
    for attempt in attempts[:size]:
        artifacts=dict(attempt.output_artifacts or {})
        events=await session.scalars(select(Event).where(Event.execution_id==execution.id,Event.node_id==node_id,
            Event.fence==attempt.fence,Event.kind=='artifact').order_by(Event.sequence))
        for event in events:
            artifacts[event.payload['artifact_name']]={'file_id':event.payload['file_id'],'size_bytes':event.payload['size_bytes']}
        container=await session.scalar(select(Container).where(Container.execution_id==execution.id,Container.node_id==node_id,
            Container.fence==attempt.fence,Container.role=='plugin'))
        values.append(pb.NodeAttempt(id=attempt.id,number=attempt.number,fence=attempt.fence,state=attempt.state,
            started_at=timestamp(attempt.started_at),finished_at=timestamp(attempt.finished_at),error_message=attempt.error_message or '',
            bytes_streamed_in=attempt.bytes_streamed_in,bytes_streamed_out=attempt.bytes_streamed_out,
            chunks_processed=attempt.chunks_processed,execution_time_ms=attempt.execution_time_ms,
            artifacts=[pb.ArtifactInfo(name=name,file_id=data['file_id'] if isinstance(data,dict) else str(data),
                size_bytes=data.get('size_bytes',0) if isinstance(data,dict) else 0) for name,data in artifacts.items()],
            container_id=container.container_id or '' if container else '',worker_id=container.daemon_id if container else '',
            image=container.image if container else '',log_bytes=attempt.log_bytes,logs_truncated=attempt.logs_truncated))
    return pb.NodeDetails(node_id=node_id,plugin_id=node.plugin_id,plugin_version=node.plugin_version,state=node.state,
        name=definition.get('name',''),description=definition.get('description',''),
        parameters_json=json.dumps(definition.get('parameters',{}),ensure_ascii=False,sort_keys=True),
        input_mapping_json=json.dumps(definition.get('input_mapping',[]),ensure_ascii=False),
        incoming_edges=[pb.WorkflowEdge(**edge) for edge in execution.graph_json['edges'] if edge['to_node_id']==node_id],
        attempts=values,has_more_attempts=len(attempts)>size,checkpoint_ready=node.checkpoint_ready)


async def attempt_row(session,request,context):
    if request.attempt_number<1: await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Positive attempt number is required')
    attempt=await session.scalar(select(Attempt).where(Attempt.execution_id==request.execution_id,
        Attempt.node_id==request.node_id,Attempt.number==request.attempt_number))
    if attempt is None: await context.abort(grpc.StatusCode.NOT_FOUND,'Node attempt not found')
    return attempt


async def read_logs(session,request,context,size,*,before_sequence=None):
    attempt=await attempt_row(session,request,context)
    rows=list(await session.scalars(select(Event).where(Event.execution_id==request.execution_id,
        Event.node_id==request.node_id,Event.fence==attempt.fence,Event.kind=='log',Event.sequence>request.after_sequence,
        *([Event.sequence<=before_sequence] if before_sequence is not None else []))
        .order_by(Event.sequence).limit(size+1)))
    secrets=secret_values()
    entries=[pb.NodeLogEntry(sequence=row.sequence,timestamp=timestamp(row.created_at),level=row.payload['level'],
        stream=row.payload['fields'].get('stream','event'),message=sanitize(row.payload['message'],secrets),
        fields=sanitize_fields(row.payload['fields'],secrets)) for row in rows[:size]]
    return pb.NodeLogsResponse(entries=entries,next_sequence=entries[-1].sequence if entries else request.after_sequence,
        has_more=len(rows)>size,truncated=attempt.logs_truncated)
