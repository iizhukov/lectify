"""Durable node report replay plus explicitly marked current-state snapshots."""
import asyncio
import json
from datetime import timezone

import grpc
from sqlalchemy import select

from generated.protos.server import index_pb2 as pb
from src.models import NodeEventModel, WorkflowExecutionModel


def epoch(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


async def stream_events(factory, execution_id, after_sequence, context, user_id, admin, *, interval=0.25):
    if after_sequence < 0:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Event cursor must be nonnegative')
    cursor, previous_state = after_sequence, None
    kinds = {'progress':pb.EVENT_TYPE_NODE_PROGRESS, 'log':pb.EVENT_TYPE_LOG_EMITTED,
        'metrics':pb.EVENT_TYPE_METRICS_REPORTED, 'artifact':pb.EVENT_TYPE_ARTIFACT_SAVED}
    while True:
        async with factory() as session:
            # Read state first. If terminal, all guarded node reports committed
            # before that transition, so the following query can drain them.
            execution = await session.get(WorkflowExecutionModel, execution_id)
            if execution is None or (not admin and execution.user_id != user_id):
                await context.abort(grpc.StatusCode.NOT_FOUND, 'Execution not found')
            state = execution.state
            snapshot = pb.ExecutionEvent(execution_id=execution_id,event_type=pb.EVENT_TYPE_STATE_CHANGED,
                timestamp=epoch(execution.updated_at),message='Execution state: '+state,
                progress_percent=execution.total_progress, metadata={'state':state,'snapshot':'true'})
            reports = list(await session.scalars(select(NodeEventModel).where(
                NodeEventModel.execution_id == execution_id, NodeEventModel.sequence > cursor,
            ).order_by(NodeEventModel.sequence).limit(100)))
            events = [pb.ExecutionEvent(execution_id=execution_id,node_id=row.node_id,
                event_type=kinds[row.kind],timestamp=epoch(row.created_at),sequence=row.sequence,
                message=str(row.payload.get('message', row.payload.get('artifact_name',''))),
                progress_percent=row.payload.get('percent',0),
                metadata={'event_id':row.event_id,'payload_json':json.dumps(row.payload,ensure_ascii=False,allow_nan=False)},
            ) for row in reports]
        # Never retain a DB transaction while waiting for the network consumer.
        for event in events:
            yield event
            cursor = event.sequence
        if len(events) == 100:
            continue
        if state != previous_state:
            yield snapshot
            previous_state = state
        if state in ('COMPLETED','FAILED','CANCELLED'):
            return
        await asyncio.sleep(interval)
