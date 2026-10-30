import asyncio
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional
import grpc
from google.protobuf.json_format import MessageToDict
from sqlalchemy import select, update

from generated.grpc_server.grpc_app import OrchestratorServiceBase
from generated.protos.server import index_pb2 as pb
from generated.db.connection import get_session_factory
from generated.logger import get_logger

from src.models import (
    WorkflowExecutionModel,
    WorkflowDispatchModel,
    WorkflowNodeExecutionModel,
    PluginRegistryModel,
    utc_now,
)
from src.engine.dispatch import claim, renew
from src.engine.dag import WorkflowDAG, DAGValidationError
from src.engine.stream_router import StreamRouter
from src.engine.docker_runner import ContainerLifecycleManager
from src.flags import flags

log = get_logger("orchestrator_service")


class OrchestratorServiceImpl(OrchestratorServiceBase):
    def __init__(self) -> None:
        self.worker_id = str(uuid.uuid4())
        self.container_manager = ContainerLifecycleManager(use_mock=True)
        self._active_routers: Dict[str, StreamRouter] = {}
        self._execution_tasks: Dict[str, asyncio.Task] = {}
        self._event_subscribers: Dict[str, List[asyncio.Queue]] = {}

    async def StartExecution(
        self,
        request: pb.StartExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.StartExecutionResponse:
        execution_id = request.execution_id or str(uuid.uuid4())
        workflow_id = request.workflow_id or "default_workflow"

        log.info(
            "start_execution_received",
            execution_id=execution_id,
            workflow_id=workflow_id,
            user_id=request.user_id,
        )

        nodes_data = [
            {
                "id": node.id,
                "plugin_id": node.plugin_id,
                "plugin_version": node.plugin_version or "0.1.0",
                "parameters": dict(node.parameters),
                "input_bindings": dict(node.input_bindings),
            }
            for node in request.graph.nodes
        ]
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

        # Persist execution & node records to database
        session_factory = get_session_factory()
        async with session_factory() as session:
            exec_model = WorkflowExecutionModel(
                id=execution_id,
                workflow_id=workflow_id,
                user_id=request.user_id,
                state="RUNNING",
                graph_json={"nodes": nodes_data, "edges": edges_data},
                initial_inputs=dict(request.initial_inputs),
            )
            session.add(exec_model)
            await session.flush()
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

            await session.commit()

        # Initialize StreamRouter for execution
        router = StreamRouter(execution_id=execution_id)
        self._active_routers[execution_id] = router

        # Launch execution background task
        task = asyncio.create_task(self._run_owned_pipeline(
            execution_id, sorted_nodes, dag, dict(request.initial_inputs),
        ))
        self._execution_tasks[execution_id] = task
        task.add_done_callback(lambda completed, key=execution_id: self._execution_finished(key, completed))

        started_at = int(time.time())
        return pb.StartExecutionResponse(
            execution_id=execution_id,
            state=pb.EXECUTION_STATE_RUNNING,
            started_at=started_at,
        )

    def _execution_finished(self, execution_id, task):
        if self._execution_tasks.get(execution_id) is task:
            self._execution_tasks.pop(execution_id, None)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                log.error("execution_task_failed", execution_id=execution_id)

    async def _run_owned_pipeline(self, execution_id, sorted_nodes, dag, initial_inputs):
        factory = get_session_factory()
        async with factory() as session:
            fence = await claim(session, execution_id, self.worker_id, int(time.time()))
            await session.commit()
        if fence is None:
            return

        async def heartbeat():
            while True:
                await asyncio.sleep(10)
                async with factory() as session:
                    owned = await renew(session, execution_id, self.worker_id, fence, int(time.time()))
                    await session.commit()
                if not owned:
                    return

        pipeline = asyncio.create_task(self._run_execution_pipeline(execution_id, sorted_nodes, dag, initial_inputs))
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

    async def _run_execution_pipeline(
        self,
        execution_id: str,
        sorted_nodes: List[Dict[str, Any]],
        dag: WorkflowDAG,
        initial_inputs: Dict[str, str],
    ) -> None:
        log.info("pipeline_started", execution_id=execution_id, node_count=len(sorted_nodes))
        session_factory = get_session_factory()

        try:
            for idx, node_def in enumerate(sorted_nodes):
                async with session_factory() as session:
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
                    stmt = select(WorkflowNodeExecutionModel).where(
                        WorkflowNodeExecutionModel.execution_id == execution_id,
                        WorkflowNodeExecutionModel.node_id == node_id,
                    )
                    res = await session.execute(stmt)
                    node_model = res.scalar_one_or_none()
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
                    stmt = select(WorkflowNodeExecutionModel).where(
                        WorkflowNodeExecutionModel.execution_id == execution_id,
                        WorkflowNodeExecutionModel.node_id == node_id,
                    )
                    res = await session.execute(stmt)
                    node_model = res.scalar_one_or_none()
                    if node_model:
                        node_model.state = "COMPLETED"
                        node_model.progress_percent = 100
                        node_model.output_artifacts = result.get("artifacts", {})
                        await session.commit()

                # Update total execution progress
                total_progress = int(((idx + 1) / len(sorted_nodes)) * 100)
                async with session_factory() as session:
                    stmt = select(WorkflowExecutionModel).where(WorkflowExecutionModel.id == execution_id)
                    res = await session.execute(stmt)
                    exec_model = res.scalar_one_or_none()
                    if exec_model:
                        exec_model.total_progress = total_progress
                        await session.commit()

            # A late worker must not overwrite cancellation or another terminal state.
            async with session_factory() as session:
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
                changed = await session.execute(update(WorkflowExecutionModel).where(
                    WorkflowExecutionModel.id == execution_id,
                    WorkflowExecutionModel.state == "RUNNING",
                ).values(state="FAILED", error_message=str(e), finished_at=utc_now()))
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
        session_factory = get_session_factory()
        async with session_factory() as session:
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
                else:
                    await session.commit()

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
        q: asyncio.Queue = asyncio.Queue()
        if request.execution_id not in self._event_subscribers:
            self._event_subscribers[request.execution_id] = []
        self._event_subscribers[request.execution_id].append(q)

        try:
            while True:
                event = await q.get()
                yield event
                if event.event_type == pb.EVENT_TYPE_STATE_CHANGED and "completed" in event.message.lower():
                    break
        finally:
            if request.execution_id in self._event_subscribers:
                self._event_subscribers[request.execution_id].remove(q)

    async def PauseExecution(
        self,
        request: pb.PauseExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.PauseExecutionResponse:
        return pb.PauseExecutionResponse(success=True, state=pb.EXECUTION_STATE_PAUSED)

    async def ResumeExecution(
        self,
        request: pb.ResumeExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.ResumeExecutionResponse:
        return pb.ResumeExecutionResponse(success=True, state=pb.EXECUTION_STATE_RUNNING)

    async def RetryNode(
        self,
        request: pb.RetryNodeRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.RetryNodeResponse:
        return pb.RetryNodeResponse(success=True, state=pb.NODE_STATE_PROCESSING)

    async def RegisterPluginManifest(
        self,
        request: pb.RegisterPluginManifestRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.RegisterPluginManifestResponse:
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
