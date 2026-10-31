"""Capability/fence guarded durable node reports. No subscriber-memory authority."""
import hashlib
import hmac
import json
import math
import re

import grpc
from sqlalchemy import select

from generated.protos.server import index_pb2 as pb
from src.engine.dispatch import guard_execution_write,database_epoch
from src.models import NodeEventModel, WorkflowDispatchModel, WorkflowNodeExecutionModel,ExecutionCredentialModel,WorkflowExecutionModel

_ID = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.:-]*$')
_METRIC = re.compile(r'^[A-Za-z_:][A-Za-z0-9_:]{0,127}$')


def _pairs(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError('Duplicate event key')
        output[key] = value
    return output


def _constant(value):
    raise ValueError('Invalid event number')


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError('Invalid event text')


def _mapping(value, count, value_limit):
    if not isinstance(value, dict) or len(value) > count:
        raise ValueError('Invalid event fields')
    for key, item in value.items():
        _text(key, 128)
        if not key:
            raise ValueError('Invalid field name')
        _text(item, value_limit)


def _payload(kind, raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 32768:
        raise ValueError('Event payload exceeds limit')
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError('Event payload must be an object')
    if kind == 'progress':
        if set(value) != {'percent', 'message'} or type(value['percent']) is not int or not 0 <= value['percent'] <= 100:
            raise ValueError('Invalid progress event')
        _text(value['message'], 4096)
    elif kind == 'log':
        if set(value) != {'level', 'message', 'fields'} or value['level'] not in ('DEBUG','INFO','WARNING','ERROR','CRITICAL'):
            raise ValueError('Invalid log event')
        _text(value['message'], 4096)
        _mapping(value['fields'], 32, 4096)
    elif kind == 'metrics':
        if set(value) != {'gauges','counters'} or not all(isinstance(group, dict) for group in value.values()):
            raise ValueError('Invalid metrics event')
        if sum(len(group) for group in value.values()) > 64:
            raise ValueError('Too many event metrics')
        for category, group in value.items():
            for key, number in group.items():
                if (not isinstance(key, str) or not _METRIC.fullmatch(key)
                        or type(number) not in (int,float) or not math.isfinite(number)
                        or category == 'counters' and number < 0):
                    raise ValueError('Invalid event metric')
    elif kind == 'artifact':
        if set(value) != {'artifact_name','file_id','size_bytes'}:
            raise ValueError('Invalid artifact event')
        name, file_id = value['artifact_name'], value['file_id']
        if not isinstance(name, str) or len(name) > 128 or not _ID.fullmatch(name):
            raise ValueError('Invalid artifact name')
        # File-service IDs are opaque UUIDs; a path/URL is never accepted here.
        import uuid
        try:
            if not isinstance(file_id, str) or str(uuid.UUID(file_id)) != file_id:
                raise ValueError()
        except (ValueError, AttributeError):
            raise ValueError('Invalid artifact file ID') from None
        if type(value['size_bytes']) is not int or not 0 <= value['size_bytes'] <= 256 * 1048576:
            raise ValueError('Invalid artifact size')
    else:
        raise ValueError('Unknown node event kind')
    return value


async def report_node_event(factory, request, context):
    try:
        for value, maximum in ((request.execution_id,36),(request.node_id,64),(request.owner,128),(request.event_id,128)):
            if not isinstance(value, str) or len(value) > maximum or not _ID.fullmatch(value):
                raise ValueError('Invalid event scope')
        if request.fence <= 0:
            raise ValueError('Positive event fence required')
        if not 32 <= len(request.report_token) <= 512 or not re.fullmatch(r'[A-Za-z0-9_-]+', request.report_token):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Reporting capability required')
        payload = _payload(request.kind, request.payload_json)
        serialized = json.dumps({'node_id':request.node_id,'kind':request.kind,'payload':payload},
                                ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        supplied = hashlib.sha256(request.report_token.encode('ascii')).hexdigest()
    except (ValueError, TypeError, OverflowError, RecursionError):
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid node event payload or scope')
    async with factory() as session:
        # DB-clock guard locks dispatch+execution until commit. No worker clock,
        # user-ID metadata or in-process subscriber state grants authority.
        if not await guard_execution_write(session, request.execution_id, (request.owner, request.fence)):
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, 'Execution lease is not active')
        dispatch = await session.get(WorkflowDispatchModel, request.execution_id)
        if (dispatch.report_token_fence != request.fence or not dispatch.report_token_hash
                or not hmac.compare_digest(dispatch.report_token_hash, supplied)):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Reporting capability is invalid')
        required = await session.scalar(select(WorkflowExecutionModel.credentials_required).where(
            WorkflowExecutionModel.id == request.execution_id))
        if required or dispatch.report_token_ciphertext is not None:
            live = await session.scalar(select(ExecutionCredentialModel.execution_id).where(
                ExecutionCredentialModel.execution_id == request.execution_id,
                ExecutionCredentialModel.expires_at > database_epoch(session)))
            if live is None:
                await context.abort(grpc.StatusCode.UNAUTHENTICATED,'Reporting capability expired')
        existing = (await session.execute(select(NodeEventModel).where(
            NodeEventModel.execution_id == request.execution_id, NodeEventModel.event_id == request.event_id))).scalar_one_or_none()
        if existing is not None:
            if not hmac.compare_digest(existing.content_hash, fingerprint):
                await context.abort(grpc.StatusCode.ALREADY_EXISTS, 'Event ID already used for different content')
            sequence = existing.sequence
            await session.commit()
            return pb.ReportNodeEventResponse(accepted=True,event_id=request.event_id,sequence=sequence)
        node = (await session.execute(select(WorkflowNodeExecutionModel).where(
            WorkflowNodeExecutionModel.execution_id == request.execution_id,
            WorkflowNodeExecutionModel.node_id == request.node_id))).scalar_one_or_none()
        if node is None or node.state not in ('PROVISIONING','BUFFERING','PROCESSING'):
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, 'Node assignment is not active')
        if request.kind == 'progress':
            if node.state != 'PROCESSING':
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION, 'Node is not processing')
            if payload['percent'] >= node.progress_percent:
                node.progress_percent = payload['percent']
                # Existing status column is a 256-character projection. Full
                # message remains durable and lossless in the event record.
                node.progress_message = payload['message'][:256]
        elif request.kind == 'artifact':
            artifacts = dict(node.output_artifacts or {})
            previous = artifacts.get(payload['artifact_name'])
            artifact = {'file_id':payload['file_id'],'size_bytes':payload['size_bytes']}
            if previous is not None and previous != artifact:
                await context.abort(grpc.StatusCode.ALREADY_EXISTS, 'Artifact name already bound')
            artifacts[payload['artifact_name']] = artifact
            node.output_artifacts = artifacts
        event = NodeEventModel(execution_id=request.execution_id,node_id=request.node_id,event_id=request.event_id,
            owner=request.owner,fence=request.fence,kind=request.kind,payload=payload,content_hash=fingerprint)
        session.add(event)
        await session.flush()
        sequence = event.sequence
        await session.commit()
    return pb.ReportNodeEventResponse(accepted=True,event_id=request.event_id,sequence=sequence)
