"""Owned workflow/node templates and immutable snapshots; transport is generated."""
import asyncio
import hashlib
import inspect
import json
import time
import uuid

import grpc
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from generated.db.connection import get_session_factory
from generated.grpc_server.grpc_app import WorkflowServiceBase
from generated.protos.server import index_pb2 as pb
from generated.workflow_validation import RegistryUnavailableError, validate_graph
from src.models import NodeTemplate, Workflow, WorkflowSnapshot


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Nonfinite JSON number')


class WorkflowServiceImpl(WorkflowServiceBase):
    def __init__(self, *, session_factory=None, registry_provider=None, clock=time.time):
        self._factory = session_factory
        self._registry_provider = registry_provider
        self._clock = clock

    def _sessions(self):
        return self._factory or get_session_factory()

    async def _principal(self, context):
        principal = getattr(context, 'lectify_principal', None)
        user = getattr(principal, 'user_id', None)
        if not isinstance(user, str) or not 1 <= len(user) <= 128:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Verified user identity required')
        return user, getattr(principal, 'is_admin', False) is True

    async def _text(self, name, description, context):
        if not name.strip() or len(name) > 200 or len(description) > 4096:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Name or description exceeds limits')

    async def _expected(self, expected, actual, context):
        if expected <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Positive expected_version required')
        if expected != actual:
            await context.abort(grpc.StatusCode.ABORTED, 'Resource version changed')

    @staticmethod
    def _readable(model, user):
        conditions = [model.owner_id.is_(None), model.owner_id == user]
        if model is Workflow:
            conditions.append(model.is_public.is_(True))
        return or_(*conditions)

    async def _row(self, session, model, resource_id, user, context):
        row = (await session.execute(select(model).where(model.id == resource_id,
            self._readable(model, user)))).scalar_one_or_none()
        if row is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, 'Resource not found')
        return row

    async def _writable(self, row, user, admin, context):
        if row.owner_id != user and not (row.owner_id is None and admin):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Resource is read only')

    async def _validate_graph(self, graph, context):
        try:
            if self._registry_provider is None:
                from src.registry import registry_schemas
                schemas = registry_schemas(graph, context)
            else:
                schemas = self._registry_provider(graph)
            if inspect.isawaitable(schemas):
                schemas = await asyncio.wait_for(schemas, timeout=5)
            return validate_graph(graph, schemas)
        except RegistryUnavailableError:
            await context.abort(grpc.StatusCode.UNAVAILABLE, 'Plugin registry validation unavailable')
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid workflow graph or plugin configuration')
        except asyncio.CancelledError:
            raise
        except Exception:
            await context.abort(grpc.StatusCode.UNAVAILABLE, 'Plugin registry validation unavailable')

    async def _graph(self, message, context):
        if message.ByteSize() > 1048576:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Workflow graph exceeds limit')
        nodes = []
        try:
            for node in message.nodes:
                params = json.loads(node.parameters_json or '{}', parse_constant=_invalid_constant, object_pairs_hook=_pairs)
                nodes.append({'id': node.id, 'plugin_id': node.plugin_id, 'plugin_version': node.plugin_version,
                    'name': node.name, 'description': node.description, 'parameters': params,
                    'input_mapping': [{'target_field': item.target_field, 'source': item.source,
                        'transform': item.transform or 'passthrough'} for item in node.input_mapping], 'prompt_id': node.prompt_id})
        except (ValueError, RecursionError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid node parameters JSON')
        graph = {'nodes': nodes, 'edges': [{'from_node_id': edge.from_node_id, 'from_output': edge.from_output,
            'to_node_id': edge.to_node_id, 'to_input': edge.to_input} for edge in message.edges]}
        return await self._validate_graph(graph, context)

    @staticmethod
    def _graph_message(graph):
        return pb.WorkflowGraph(nodes=[pb.GraphNode(id=node['id'], plugin_id=node['plugin_id'],
            plugin_version=node['plugin_version'], name=node['name'], description=node['description'],
            parameters_json=canonical(node['parameters']), input_mapping=[pb.InputMapping(**item) for item in node['input_mapping']],
            prompt_id=node['prompt_id']) for node in graph['nodes']], edges=[pb.GraphEdge(**edge) for edge in graph['edges']])

    def _workflow_message(self, row):
        return pb.Workflow(id=row.id, owner_id=row.owner_id or '', name=row.name, description=row.description,
            graph=self._graph_message(row.graph), is_public=row.is_public, version=row.version,
            created_at=row.created_at, updated_at=row.updated_at)

    @staticmethod
    def _node_message(row):
        return pb.NodeTemplate(id=row.id, owner_id=row.owner_id or '', plugin_id=row.plugin_id,
            plugin_version=row.plugin_version, name=row.name, description=row.description,
            parameters_json=canonical(row.parameters), input_mapping=[pb.InputMapping(**item) for item in row.input_mapping],
            prompt_id=row.prompt_id, version=row.version, created_at=row.created_at, updated_at=row.updated_at)

    def _snapshot_message(self, row):
        return pb.WorkflowSnapshot(id=row.id, workflow_id=row.workflow_id, workflow_version=row.workflow_version,
            created_by=row.created_by, name=row.name, description=row.description,
            graph=self._graph_message(row.graph), content_hash=row.content_hash, created_at=row.created_at)

    async def CreateWorkflow(self, request, context):
        user, admin = await self._principal(context)
        if request.global_workflow and not admin:
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Global workflows require administrator')
        await self._text(request.name, request.description, context)
        graph = await self._graph(request.graph, context)
        now = int(self._clock())
        row = Workflow(id=str(uuid.uuid4()), owner_id=None if request.global_workflow else user,
            name=request.name, description=request.description, graph=graph,
            is_public=request.is_public or request.global_workflow, version=1, created_at=now, updated_at=now)
        async with self._sessions()() as session:
            session.add(row)
            await session.commit()
            return self._workflow_message(row)

    async def GetWorkflow(self, request, context):
        user, _ = await self._principal(context)
        async with self._sessions()() as session:
            return self._workflow_message(await self._row(session, Workflow, request.id, user, context))

    async def _list(self, model, request, context):
        user, _ = await self._principal(context)
        size = request.page_size or 50
        if not 1 <= size <= 100 or not 0 <= request.offset <= 100000:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid pagination')
        condition = model.owner_id == user if request.own_only else self._readable(model, user)
        async with self._sessions()() as session:
            rows = (await session.execute(select(model).where(condition).order_by(model.created_at, model.id)
                .offset(request.offset).limit(size + 1))).scalars().all()
        return rows[:size], request.offset + size if len(rows) > size else 0

    async def ListWorkflows(self, request, context):
        rows, offset = await self._list(Workflow, request, context)
        return pb.WorkflowList(workflows=[self._workflow_message(row) for row in rows], next_offset=offset)

    async def UpdateWorkflow(self, request, context):
        user, admin = await self._principal(context)
        await self._text(request.name, request.description, context)
        async with self._sessions()() as session:
            row = await self._row(session, Workflow, request.id, user, context)
            await self._writable(row, user, admin, context)
            await self._expected(request.expected_version, row.version, context)
            graph = await self._graph(request.graph, context)
            changed = (await session.execute(update(Workflow).where(Workflow.id == row.id,
                Workflow.version == request.expected_version).values(name=request.name, description=request.description,
                graph=graph, is_public=request.is_public or row.owner_id is None,
                version=Workflow.version + 1, updated_at=int(self._clock())).returning(Workflow.id))).scalar_one_or_none()
            if changed is None:
                await session.rollback()
                await context.abort(grpc.StatusCode.ABORTED, 'Resource version changed')
            await session.commit()
            await session.refresh(row)
            return self._workflow_message(row)

    async def _delete(self, model, request, context):
        user, admin = await self._principal(context)
        async with self._sessions()() as session:
            row = await self._row(session, model, request.id, user, context)
            await self._writable(row, user, admin, context)
            await self._expected(request.expected_version, row.version, context)
            changed = (await session.execute(delete(model).where(model.id == row.id,
                model.version == request.expected_version).returning(model.id))).scalar_one_or_none()
            if changed is None:
                await session.rollback()
                await context.abort(grpc.StatusCode.ABORTED, 'Resource version changed')
            await session.commit()
        return pb.OperationResponse(accepted=True)

    async def DeleteWorkflow(self, request, context):
        return await self._delete(Workflow, request, context)

    async def _node_values(self, request, context):
        await self._text(request.name, request.description, context)
        graph = await self._graph(pb.WorkflowGraph(nodes=[pb.GraphNode(id='template', plugin_id=request.plugin_id,
            plugin_version=request.plugin_version, name=request.name, description=request.description,
            parameters_json=request.parameters_json, input_mapping=request.input_mapping, prompt_id=request.prompt_id)]), context)
        return graph['nodes'][0]

    async def CreateNodeTemplate(self, request, context):
        user, admin = await self._principal(context)
        if request.global_node and not admin:
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Global nodes require administrator')
        node = await self._node_values(request, context)
        now = int(self._clock())
        row = NodeTemplate(id=str(uuid.uuid4()), owner_id=None if request.global_node else user,
            plugin_id=node['plugin_id'], plugin_version=node['plugin_version'], name=request.name,
            description=request.description, parameters=node['parameters'], input_mapping=node['input_mapping'],
            prompt_id=node['prompt_id'], version=1, created_at=now, updated_at=now)
        async with self._sessions()() as session:
            session.add(row)
            await session.commit()
            return self._node_message(row)

    async def GetNodeTemplate(self, request, context):
        user, _ = await self._principal(context)
        async with self._sessions()() as session:
            return self._node_message(await self._row(session, NodeTemplate, request.id, user, context))

    async def ListNodeTemplates(self, request, context):
        rows, offset = await self._list(NodeTemplate, request, context)
        return pb.NodeTemplateList(nodes=[self._node_message(row) for row in rows], next_offset=offset)

    async def UpdateNodeTemplate(self, request, context):
        user, admin = await self._principal(context)
        async with self._sessions()() as session:
            row = await self._row(session, NodeTemplate, request.id, user, context)
            await self._writable(row, user, admin, context)
            await self._expected(request.expected_version, row.version, context)
            node = await self._node_values(request, context)
            changed = (await session.execute(update(NodeTemplate).where(NodeTemplate.id == row.id,
                NodeTemplate.version == request.expected_version).values(plugin_id=node['plugin_id'],
                plugin_version=node['plugin_version'], name=request.name, description=request.description,
                parameters=node['parameters'], input_mapping=node['input_mapping'], prompt_id=node['prompt_id'],
                version=NodeTemplate.version + 1, updated_at=int(self._clock())).returning(NodeTemplate.id))).scalar_one_or_none()
            if changed is None:
                await session.rollback()
                await context.abort(grpc.StatusCode.ABORTED, 'Resource version changed')
            await session.commit()
            await session.refresh(row)
            return self._node_message(row)

    async def DeleteNodeTemplate(self, request, context):
        return await self._delete(NodeTemplate, request, context)

    async def _guard_source(self, session, row, user, context):
        # Registry lookups may await remote I/O. Recheck version+visibility and
        # obtain a row write lock before copying it into a new persistent record.
        claimed = (await session.execute(update(Workflow).where(Workflow.id == row.id,
            Workflow.version == row.version, self._readable(Workflow, user))
            .values(version=Workflow.version).returning(Workflow.id))).scalar_one_or_none()
        if claimed is None:
            await session.rollback()
            await context.abort(grpc.StatusCode.ABORTED, 'Source workflow changed')

    async def CreateSnapshot(self, request, context):
        user, _ = await self._principal(context)
        if not request.request_key or len(request.request_key) > 128 or request.expected_version <= 0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Bounded request_key and positive expected_version required')
        async with self._sessions()() as session:
            existing = (await session.execute(select(WorkflowSnapshot).where(
                WorkflowSnapshot.created_by == user, WorkflowSnapshot.request_key == request.request_key))).scalar_one_or_none()
            if existing is not None:
                if existing.workflow_id != request.workflow_id or existing.workflow_version != request.expected_version:
                    await context.abort(grpc.StatusCode.ALREADY_EXISTS, 'Snapshot request key already used')
                return self._snapshot_message(existing)
            row = await self._row(session, Workflow, request.workflow_id, user, context)
            await self._expected(request.expected_version, row.version, context)
            graph = await self._validate_graph(json.loads(canonical(row.graph)), context)
            await self._guard_source(session, row, user, context)
            payload = {'workflow_id': row.id, 'workflow_version': row.version,
                       'name': row.name, 'description': row.description, 'graph': graph}
            snapshot = WorkflowSnapshot(id=str(uuid.uuid4()), workflow_id=row.id, workflow_version=row.version,
                created_by=user, request_key=request.request_key, name=row.name, description=row.description,
                graph=graph, content_hash=hashlib.sha256(canonical(payload).encode()).hexdigest(), created_at=int(self._clock()))
            session.add(snapshot)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = (await session.execute(select(WorkflowSnapshot).where(
                    WorkflowSnapshot.created_by == user, WorkflowSnapshot.request_key == request.request_key))).scalar_one_or_none()
                if existing is None or existing.workflow_id != request.workflow_id or existing.workflow_version != request.expected_version:
                    await context.abort(grpc.StatusCode.ALREADY_EXISTS, 'Snapshot request key already used')
                return self._snapshot_message(existing)
            return self._snapshot_message(snapshot)

    async def GetSnapshot(self, request, context):
        user, _ = await self._principal(context)
        async with self._sessions()() as session:
            row = (await session.execute(select(WorkflowSnapshot).where(
                WorkflowSnapshot.id == request.id, WorkflowSnapshot.created_by == user))).scalar_one_or_none()
            if row is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, 'Snapshot not found')
            return self._snapshot_message(row)

    async def ForkWorkflow(self, request, context):
        user, _ = await self._principal(context)
        async with self._sessions()() as session:
            source = await self._row(session, Workflow, request.id, user, context)
            await self._expected(request.expected_version, source.version, context)
            name = request.name or source.name[:193] + ' (copy)'
            await self._text(name, source.description, context)
            graph = await self._validate_graph(json.loads(canonical(source.graph)), context)
            await self._guard_source(session, source, user, context)
            now = int(self._clock())
            row = Workflow(id=str(uuid.uuid4()), owner_id=user, name=name, description=source.description,
                           graph=graph, is_public=False, version=1, created_at=now, updated_at=now)
            session.add(row)
            await session.commit()
            return self._workflow_message(row)
