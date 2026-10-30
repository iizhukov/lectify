import asyncio
import time
import uuid
import re
import json
from contextlib import aclosing
from typing import Any, AsyncIterator, Dict, List, Optional
import grpc
from google.protobuf.json_format import MessageToDict
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from generated.grpc_server.grpc_app import OrchestratorServiceBase
from generated.protos.server import index_pb2 as pb
from generated.db.connection import get_session_factory
from generated.db.transactions import run_transaction
from generated.logger import get_logger

from src.models import (
    WorkflowExecutionModel,
    WorkflowDispatchModel,
    WorkflowNodeExecutionModel,
    PluginRegistryModel,
    utc_now,
)
from src.engine.dispatch import claim, renew, guard_execution_write, pending_executions
from src.node_events import report_node_event
from src.execution_events import stream_events, epoch
from src.engine.dag import WorkflowDAG, DAGValidationError
from src.engine.stream_router import StreamRouter
from src.engine.docker_runner import ContainerLifecycleManager
from generated.stream_pipeline import run_streaming_graph
from src.flags import flags

log = get_logger("orchestrator_service")


def _json_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def _invalid_number(value):
    raise ValueError('Non-finite JSON value')


def _node_data(node):
    if node.parameters_json and node.parameters:
        raise ValueError('Specify either typed JSON or legacy parameters')
    for raw in (node.parameters_json, node.input_mapping_json):
        if len(raw.encode('utf-8')) > 65536:
            raise ValueError('Node JSON exceeds limit')
    parameters = json.loads(node.parameters_json, object_pairs_hook=_json_pairs,
        parse_constant=_invalid_number) if node.parameters_json else dict(node.parameters)
    mappings = json.loads(node.input_mapping_json, object_pairs_hook=_json_pairs,
        parse_constant=_invalid_number) if node.input_mapping_json else []
    if not isinstance(parameters, dict) or not isinstance(mappings, list) or len(mappings) > 128:
        raise ValueError('Invalid node parameters or input mappings')
    if len(json.dumps(parameters, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 65536:
        raise ValueError('Node parameters exceed limit')
    for mapping in mappings:
        if (not isinstance(mapping, dict) or set(mapping) != {'target_field','source','transform'}
                or any(not isinstance(value, str) or len(value) > 4096 for value in mapping.values())):
            raise ValueError('Invalid frozen input mapping')
    result = {'id':node.id,'plugin_id':node.plugin_id,'plugin_version':node.plugin_version or '0.1.0',
        'parameters':parameters,'input_bindings':dict(node.input_bindings)}
    if mappings:
        result['input_mapping'] = mappings
    if node.prompt_id:
        result['prompt_id'] = node.prompt_id
    return result


class OrchestratorServiceImpl(OrchestratorServiceBase):
    def __init__(self, container_manager=None) -> None:
        self.worker_id = str(uuid.uuid4())
        self.container_manager = container_manager if container_manager is not None else ContainerLifecycleManager()
        self._active_routers: Dict[str, StreamRouter] = {}
        self._execution_tasks: Dict[str, asyncio.Task] = {}
        self._event_subscribers: Dict[str, List[asyncio.Queue]] = {}

    async def _principal(self, context):
        principal = getattr(context, 'lectify_principal', None)
        user_id = getattr(principal, 'user_id', None)
        if not isinstance(user_id, str) or not user_id or len(user_id) > 64:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Verified user identity required')
        return user_id, getattr(principal, 'is_admin', False) is True

    async def _authorize_execution(self, context, execution_id):
        user_id, admin = await self._principal(context)
        async with get_session_factory()() as session:
            owner = (await session.execute(select(WorkflowExecutionModel.user_id).where(
                WorkflowExecutionModel.id == execution_id))).one_or_none()
            if owner is None or (not admin and owner[0] != user_id):
                await context.abort(grpc.StatusCode.NOT_FOUND, 'Execution not found')

    async def StartExecution(
        self,
        request: pb.StartExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.StartExecutionResponse:
        user_id, _ = await self._principal(context)
        if request.user_id and request.user_id != user_id:
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Execution owner must match authenticated user')
        if not 1 <= len(request.graph.nodes) <= 256 or len(request.graph.edges) > 1024:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Execution graph exceeds limits')
        execution_id = request.execution_id or str(uuid.uuid4())
        workflow_id = request.workflow_id or "default_workflow"
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,35}', execution_id) or len(workflow_id) > 64:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid execution or workflow identifier')

        log.info(
            "start_execution_received",
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
        )

        try:
            nodes_data = [_node_data(node) for node in request.graph.nodes]
        except (ValueError, TypeError, RecursionError, UnicodeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid typed node configuration')
        edges_data = [
            {
                "from_node_id": edge.from_node_id,
                "from_output": edge.from_output,
                "to_node_id": edge.to_node_id,
                "to_input": edge.to_input,
            }
            for edge in request.graph.edges
        ]

        try:
            dag = WorkflowDAG(nodes=nodes_data, edges=edges_data)
            sorted_nodes = dag.topological_sort()
        except DAGValidationError as e:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
            return pb.StartExecutionResponse()

        graph_json = {"nodes": nodes_data, "edges": edges_data}
        initial_inputs = dict(request.initial_inputs)
        async def reuse(saved):
            if saved.user_id != user_id:
                await context.abort(grpc.StatusCode.NOT_FOUND, 'Execution not found')
            if (saved.workflow_id != workflow_id or saved.graph_json != graph_json
                    or saved.initial_inputs != initial_inputs):
                await context.abort(grpc.StatusCode.ALREADY_EXISTS, 'Execution ID is bound to another request')
            return pb.StartExecutionResponse(execution_id=saved.id,
                state=getattr(pb, 'EXECUTION_STATE_' + saved.state, pb.EXECUTION_STATE_UNSPECIFIED),
                started_at=epoch(saved.created_at)), False

        # Commit execution, dispatch and nodes together before external work.
        session_factory = get_session_factory()
        async def persist(session):
            existing = await session.get(WorkflowExecutionModel, execution_id)
            if existing is not None:
                return await reuse(existing)
            exec_model = WorkflowExecutionModel(
                id=execution_id,
                workflow_id=workflow_id,
                user_id=user_id,
                state="RUNNING",
                graph_json=graph_json,
                initial_inputs=initial_inputs,
            )
            session.add(exec_model)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                existing = await session.get(WorkflowExecutionModel, execution_id)
                if existing is None:
                    raise
                return await reuse(existing)
            session.add(WorkflowDispatchModel(execution_id=execution_id))

            for node in sorted_nodes:
                node_model = WorkflowNodeExecutionModel(
                    id=str(uuid.uuid4()),
                    execution_id=execution_id,
                    node_id=node["id"],
                    plugin_id=node["plugin_id"],
                    plugin_version=node.get("plugin_version", "0.1.0"),
                    state="PENDING",
                )
                session.add(node_model)

            return pb.StartExecutionResponse(execution_id=execution_id,
                state=pb.EXECUTION_STATE_RUNNING, started_at=epoch(exec_model.created_at)), True
        response, created = await run_transaction(session_factory, persist)
        if not created:
            return response

        # Launch execution background task
        task = asyncio.create_task(self._run_owned_pipeline(
            execution_id, sorted_nodes, dag, dict(request.initial_inputs),
        ))
        self._execution_tasks[execution_id] = task
        task.add_done_callback(lambda completed, key=execution_id: self._execution_finished(key, completed))

        return response

    def _execution_finished(self, execution_id, task):
        if self._execution_tasks.get(execution_id) is task:
            self._execution_tasks.pop(execution_id, None)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                log.error("execution_task_failed", execution_id=execution_id)

    async def dispatch_pending(self, limit=100):
        factory = get_session_factory()
        async with factory() as session:
            rows = await pending_executions(session, limit)
        scheduled = 0
        for row in rows:
            if row.id in self._execution_tasks:
                continue
            graph = row.graph_json
            try:
                if not isinstance(graph, dict):
                    raise DAGValidationError('Saved workflow graph must be an object')
                dag = WorkflowDAG(graph.get("nodes", []), graph.get("edges", []))
                nodes = dag.topological_sort()
                if not isinstance(row.initial_inputs, dict):
                    raise DAGValidationError('Saved workflow inputs must be an object')
            except DAGValidationError:
                # Compete for this row before declaring it failed. A different
                # replica may have claimed it since the batch was selected.
                async with factory() as session:
                    fence = await claim(session, row.id, self.worker_id)
                    if fence is not None and await guard_execution_write(
                            session, row.id, (self.worker_id, fence)):
                        await session.execute(update(WorkflowExecutionModel).where(
                            WorkflowExecutionModel.id == row.id,
                        ).values(state='FAILED', error_message='Invalid persisted workflow', finished_at=utc_now()))
                    await session.commit()
                log.error('invalid_persisted_workflow', execution_id=row.id)
                continue
            task = asyncio.create_task(self._run_owned_pipeline(row.id, nodes, dag, row.initial_inputs))
            self._execution_tasks[row.id] = task
            task.add_done_callback(lambda completed, key=row.id: self._execution_finished(key, completed))
            scheduled += 1
        return scheduled

    async def _run_owned_pipeline(self, execution_id, sorted_nodes, dag, initial_inputs):
        factory = get_session_factory()
        async with factory() as session:
            fence = await claim(session, execution_id, self.worker_id)
            await session.commit()
        if fence is None:
            return

        router = self._active_routers.setdefault(execution_id, StreamRouter(execution_id=execution_id))

        async def heartbeat():
            while True:
                await asyncio.sleep(10)
                async with factory() as session:
                    owned = await renew(session, execution_id, self.worker_id, fence)
                    await session.commit()
                if not owned:
                    return

        pipeline = asyncio.create_task(self._run_execution_pipeline(execution_id, sorted_nodes, dag, initial_inputs, (self.worker_id, fence)))
        lease = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait((pipeline, lease), return_when=asyncio.FIRST_COMPLETED)
            if lease in done:
                lease.result()
            if pipeline in done:
                await pipeline
        finally:
            for task in (pipeline, lease):
                if not task.done() and not task.cancelling():
                    task.cancel()
            await asyncio.gather(pipeline, lease, return_exceptions=True)
            await router.close_all()
            if self._active_routers.get(execution_id) is router:
                self._active_routers.pop(execution_id, None)

    async def _run_execution_pipeline(
        self,
        execution_id: str,
        sorted_nodes: List[Dict[str, Any]],
        dag: WorkflowDAG,
        initial_inputs: Dict[str, str],
        ownership=None,
    ) -> None:
        log.info("pipeline_started", execution_id=execution_id, node_count=len(sorted_nodes))
        session_factory = get_session_factory()

        try:
            if getattr(self.container_manager, 'supports_streaming', False):
                await self._run_stream_nodes(execution_id, sorted_nodes, dag, initial_inputs, ownership)
                sorted_nodes = []
            for idx, node_def in enumerate(sorted_nodes):
                async with session_factory() as session:
                    if not await guard_execution_write(session, execution_id, ownership):
                        return
                    current_state = await session.scalar(select(WorkflowExecutionModel.state).where(
                        WorkflowExecutionModel.id == execution_id,
                    ))
                    if current_state != "RUNNING":
                        return
                node_id = node_def["id"]
                plugin_id = node_def["plugin_id"]
                params = node_def.get("parameters", {})

                # Update node state to RUNNING
                async with session_factory() as session:
                    if not await guard_execution_write(session, execution_id, ownership):
                        return
                    stmt = select(WorkflowNodeExecutionModel).where(
                        WorkflowNodeExecutionModel.execution_id == execution_id,
                        WorkflowNodeExecutionModel.node_id == node_id,
                    )
                    res = await session.execute(stmt)
                    node_model = res.scalar_one_or_none()
                    if node_model and node_model.state == "COMPLETED":
                        # A replacement owner resumes durable work; it must not
                        # repeat a completed node's external side effects.
                        continue
                    if node_model:
                        node_model.state = "PROCESSING"
                        node_model.progress_percent = 10
                        await session.commit()

                def on_node_progress(percent: int, msg: str) -> None:
                    asyncio.create_task(self._broadcast_event(
                        execution_id,
                        node_id,
                        pb.EVENT_TYPE_NODE_PROGRESS,
                        msg,
                        percent,
                    ))

                result = await self.container_manager.start_plugin_node(
                    execution_id=execution_id,
                    node_id=node_id,
                    plugin_id=plugin_id,
                    parameters=params,
                    on_progress=on_node_progress,
                )

                # Update node state to COMPLETED
                async with session_factory() as session:
                    if not await guard_execution_write(session, execution_id, ownership):
                        return
                    stmt = select(WorkflowNodeExecutionModel).where(
                        WorkflowNodeExecutionModel.execution_id == execution_id,
                        WorkflowNodeExecutionModel.node_id == node_id,
                    )
                    res = await session.execute(stmt)
                    node_model = res.scalar_one_or_none()
                    if node_model:
                        node_model.state = "COMPLETED"
                        node_model.progress_percent = 100
                        node_model.output_artifacts = {**(node_model.output_artifacts or {}), **result.get("artifacts", {})}
                        await session.commit()

                # Update total execution progress
                total_progress = int(((idx + 1) / len(sorted_nodes)) * 100)
                async with session_factory() as session:
                    if not await guard_execution_write(session, execution_id, ownership):
                        return
                    stmt = select(WorkflowExecutionModel).where(WorkflowExecutionModel.id == execution_id)
                    res = await session.execute(stmt)
                    exec_model = res.scalar_one_or_none()
                    if exec_model:
                        exec_model.total_progress = total_progress
                        await session.commit()

            # A late worker must not overwrite cancellation or another terminal state.
            async with session_factory() as session:
                if not await guard_execution_write(session, execution_id, ownership):
                    return
                changed = await session.execute(update(WorkflowExecutionModel).where(
                    WorkflowExecutionModel.id == execution_id,
                    WorkflowExecutionModel.state == "RUNNING",
                ).values(state="COMPLETED", total_progress=100, finished_at=utc_now()))
                await session.commit()
                if changed.rowcount != 1:
                    return

            await self._broadcast_event(
                execution_id,
                "",
                pb.EVENT_TYPE_STATE_CHANGED,
                "Workflow execution completed successfully",
                100,
            )

        except Exception as e:
            log.error("pipeline_failed", execution_id=execution_id, error=str(e))
            async with session_factory() as session:
                if not await guard_execution_write(session, execution_id, ownership):
                    return
                changed = await session.execute(update(WorkflowExecutionModel).where(
                    WorkflowExecutionModel.id == execution_id,
                    WorkflowExecutionModel.state == "RUNNING",
                ).values(state="FAILED", error_message=str(e), finished_at=utc_now()))
                if changed.rowcount == 1:
                    await session.execute(update(WorkflowNodeExecutionModel).where(
                        WorkflowNodeExecutionModel.execution_id == execution_id,
                        WorkflowNodeExecutionModel.state.in_(("PROVISIONING", "BUFFERING", "PROCESSING")),
                    ).values(state="FAILED", error_message=str(e)))
                await session.commit()
                if changed.rowcount != 1:
                    return

            await self._broadcast_event(
                execution_id,
                "",
                pb.EVENT_TYPE_STATE_CHANGED,
                f"Workflow failed: {str(e)}",
                0,
            )


    async def _run_stream_nodes(self, execution_id, nodes, dag, initial_inputs, ownership):
        factory = get_session_factory()
        async def run_node(node, inputs):
            async def begin(session):
                if not await guard_execution_write(session, execution_id, ownership):
                    raise RuntimeError('Execution stream lease was lost')
                model = await session.scalar(select(WorkflowNodeExecutionModel).where(
                    WorkflowNodeExecutionModel.execution_id == execution_id,
                    WorkflowNodeExecutionModel.node_id == node['id']))
                if model is None:
                    raise RuntimeError('Execution node is not persisted')
                if model.state == 'COMPLETED':
                    raise RuntimeError('Completed stream node requires durable output replay')
                model.state, model.progress_percent = 'PROCESSING', 0
            await run_transaction(factory, begin)
            async with aclosing(self.container_manager.stream_node(execution_id=execution_id, node=node,
                    inputs=inputs, ownership=ownership, initial_inputs=initial_inputs)) as output:
                async for frame in output:
                    yield frame
        async def complete(node):
            async def persist(session):
                if not await guard_execution_write(session, execution_id, ownership):
                    raise RuntimeError('Execution stream lease was lost')
                await session.execute(update(WorkflowNodeExecutionModel).where(
                    WorkflowNodeExecutionModel.execution_id == execution_id,
                    WorkflowNodeExecutionModel.node_id == node['id'],
                    WorkflowNodeExecutionModel.state == 'PROCESSING',
                ).values(state='COMPLETED', progress_percent=100))
            await run_transaction(factory, persist)
        await run_streaming_graph(execution_id, nodes, dag.edges, run_node, on_node_complete=complete)

    async def _broadcast_event(
        self,
        execution_id: str,
        node_id: str,
        event_type: pb.EventType,
        message: str,
        progress_percent: int,
    ) -> None:
        event = pb.ExecutionEvent(
            execution_id=execution_id,
            node_id=node_id,
            event_type=event_type,
            timestamp=int(time.time()),
            message=message,
            progress_percent=progress_percent,
        )
        subscribers = self._event_subscribers.get(execution_id, [])
        for q in subscribers:
            await q.put(event)

    async def CancelExecution(
        self,
        request: pb.CancelExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.CancelExecutionResponse:
        await self._authorize_execution(context, request.execution_id)
        session_factory = get_session_factory()
        async def persist(session):
            stmt = select(WorkflowExecutionModel).where(WorkflowExecutionModel.id == request.execution_id)
            res = await session.execute(stmt)
            exec_model = res.scalar_one_or_none()
            if not exec_model:
                await context.abort(grpc.StatusCode.NOT_FOUND, f"Execution '{request.execution_id}' not found")
                return pb.CancelExecutionResponse()

            if exec_model.state != "CANCELLED":
                changed = await session.execute(update(WorkflowExecutionModel).where(
                    WorkflowExecutionModel.id == request.execution_id,
                    WorkflowExecutionModel.state.in_(("PENDING", "RUNNING", "PAUSED")),
                ).values(state="CANCELLED", error_message=request.reason or "Cancelled by user", finished_at=utc_now()))
                if changed.rowcount != 1:
                    await session.rollback()
                    current_state = await session.scalar(select(WorkflowExecutionModel.state).where(
                        WorkflowExecutionModel.id == request.execution_id,
                    ))
                    if current_state != "CANCELLED":
                        await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Execution is already terminal")
            await session.execute(update(WorkflowNodeExecutionModel).where(
                WorkflowNodeExecutionModel.execution_id == request.execution_id,
                WorkflowNodeExecutionModel.state.in_(("PENDING", "PROVISIONING", "BUFFERING", "PROCESSING")),
            ).values(state="CANCELLED", error_message=request.reason or "Cancelled by user"))
        await run_transaction(session_factory, persist)

        task = self._execution_tasks.get(request.execution_id)
        if task is not None and task is not asyncio.current_task():
            if not task.done() and not task.cancelling():
                task.cancel()
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
        router = self._active_routers.get(request.execution_id)
        if router is not None:
            await router.close_all()
            if self._active_routers.get(request.execution_id) is router:
                self._active_routers.pop(request.execution_id, None)

        return pb.CancelExecutionResponse(
            success=True,
            state=pb.EXECUTION_STATE_CANCELLED,
        )

    async def GetExecutionStatus(
        self,
        request: pb.GetExecutionStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.GetExecutionStatusResponse:
        await self._authorize_execution(context, request.execution_id)
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(WorkflowExecutionModel).where(WorkflowExecutionModel.id == request.execution_id)
            res = await session.execute(stmt)
            exec_model = res.scalar_one_or_none()

            if not exec_model:
                await context.abort(grpc.StatusCode.NOT_FOUND, f"Execution '{request.execution_id}' not found")
                return pb.GetExecutionStatusResponse()

            node_stmt = select(WorkflowNodeExecutionModel).where(
                WorkflowNodeExecutionModel.execution_id == request.execution_id
            )
            node_res = await session.execute(node_stmt)
            node_models = node_res.scalars().all()

        state_map = {
            "PENDING": pb.EXECUTION_STATE_PENDING,
            "RUNNING": pb.EXECUTION_STATE_RUNNING,
            "COMPLETED": pb.EXECUTION_STATE_COMPLETED,
            "FAILED": pb.EXECUTION_STATE_FAILED,
            "CANCELLED": pb.EXECUTION_STATE_CANCELLED,
            "PAUSED": pb.EXECUTION_STATE_PAUSED,
        }
        node_state_map = {
            "PENDING": pb.NODE_STATE_PENDING,
            "PROCESSING": pb.NODE_STATE_PROCESSING,
            "COMPLETED": pb.NODE_STATE_COMPLETED,
            "FAILED": pb.NODE_STATE_FAILED,
            "CANCELLED": pb.NODE_STATE_CANCELLED,
        }

        nodes_pb = [
            pb.NodeExecutionStatus(
                node_id=n.node_id,
                plugin_id=n.plugin_id,
                state=node_state_map.get(n.state, pb.NODE_STATE_PENDING),
                progress_percent=n.progress_percent,
                progress_message=n.progress_message,
                bytes_streamed_in=n.bytes_streamed_in,
                bytes_streamed_out=n.bytes_streamed_out,
                chunks_processed=n.chunks_processed,
                execution_time_ms=n.execution_time_ms,
                error_message=n.error_message or "",
                output_artifacts={k: str(v) for k, v in (n.output_artifacts or {}).items()},
            )
            for n in node_models
        ]

        return pb.GetExecutionStatusResponse(
            execution_id=exec_model.id,
            state=state_map.get(exec_model.state, pb.EXECUTION_STATE_UNSPECIFIED),
            total_progress_percent=exec_model.total_progress,
            nodes=nodes_pb,
            started_at=int(exec_model.created_at.timestamp()) if exec_model.created_at else 0,
            finished_at=int(exec_model.finished_at.timestamp()) if exec_model.finished_at else 0,
            error_message=exec_model.error_message or "",
        )

    async def StreamExecutionEvents(
        self,
        request: pb.StreamExecutionEventsRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[pb.ExecutionEvent]:
        user_id, admin = await self._principal(context)
        async with aclosing(stream_events(get_session_factory(), request.execution_id,
                request.after_sequence, context, user_id, admin)) as events:
            async for event in events:
                yield event

    async def PauseExecution(
        self,
        request: pb.PauseExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.PauseExecutionResponse:
        await self._authorize_execution(context, request.execution_id)
        await context.abort(grpc.StatusCode.UNIMPLEMENTED, 'Durable stream pause is not implemented')

    async def ResumeExecution(
        self,
        request: pb.ResumeExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.ResumeExecutionResponse:
        await self._authorize_execution(context, request.execution_id)
        await context.abort(grpc.StatusCode.UNIMPLEMENTED, 'Durable stream resume is not implemented')

    async def RetryNode(
        self,
        request: pb.RetryNodeRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.RetryNodeResponse:
        await self._authorize_execution(context, request.execution_id)
        await context.abort(grpc.StatusCode.UNIMPLEMENTED, 'Durable stream retry is not implemented')

    async def RegisterPluginManifest(
        self,
        request: pb.RegisterPluginManifestRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.RegisterPluginManifestResponse:
        _, admin = await self._principal(context)
        if not admin:
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Plugin registration requires administrator access')
        session_factory = get_session_factory()
        async with session_factory() as session:
            model = PluginRegistryModel(
                id=request.plugin_id,
                version=request.version,
                name=request.plugin_id,
                manifest_yaml=request.manifest_yaml,
            )
            await session.merge(model)
            await session.commit()

        return pb.RegisterPluginManifestResponse(
            success=True,
            message=f"Plugin '{request.plugin_id}' v{request.version} registered",
        )

    async def ListRegisteredPlugins(
        self,
        request: pb.ListRegisteredPluginsRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.ListRegisteredPluginsResponse:
        await self._principal(context)
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(PluginRegistryModel)
            if request.category:
                stmt = stmt.where(PluginRegistryModel.category == request.category)
            res = await session.execute(stmt)
            models = res.scalars().all()

        return pb.ListRegisteredPluginsResponse(
            plugins=[
                pb.PluginSummary(
                    plugin_id=m.id,
                    name=m.name,
                    version=m.version,
                    category=m.category,
                    description=m.description,
                )
                for m in models
            ]
        )

    async def ReportNodeEvent(self, request, context):
        return await report_node_event(get_session_factory(), request, context)
