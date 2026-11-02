import asyncio
import time
import uuid
import re
import json
import os
import hashlib
from contextlib import aclosing
from typing import Any, AsyncIterator, Dict, List, Optional
import grpc
from google.protobuf.json_format import MessageToDict
from sqlalchemy import select, update, func
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
from src.engine.dispatch import claim, renew, guard_execution_write, pending_executions,database_epoch
from src.node_events import report_node_event
from src.execution_events import stream_events, epoch
from src.engine.dag import WorkflowDAG, DAGValidationError
from src.engine.stream_router import StreamRouter
from src.engine.docker_runner import ContainerLifecycleManager
from generated.stream_pipeline import run_streaming_graph
from generated.plugin_manifest import parse_plugin_manifest
from generated.credential_cipher import CredentialCipher
from generated.user_auth.client import delegated_metadata
from src.engine.credentials import ExecutionCredentials
from src.engine.checkpoints import StreamCheckpoints
from src.engine.lifecycle import locked_execution,revoke,reset_unfinished,descendants
from src.engine import attempts as attempt_history
from src import details as execution_details
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
    if len(node.name)>200 or len(node.description)>4096: raise ValueError('Node text exceeds limit')
    if node.name: result['name']=node.name
    if node.description: result['description']=node.description
    if mappings:
        result['input_mapping'] = mappings
    if node.prompt_id:
        result['prompt_id'] = node.prompt_id
    return result


class OrchestratorServiceImpl(OrchestratorServiceBase):
    def __init__(self, container_manager=None, *, credential_store=None) -> None:
        self.worker_id = str(uuid.uuid4())
        self.credentials = credential_store
        key = os.environ.get('LECTIFY_EXECUTION_CREDENTIAL_KEY')
        if self.credentials is None and key is not None:
            self.credentials = ExecutionCredentials(CredentialCipher(key))
        if container_manager is None and os.environ.get('LECTIFY_DEPLOYMENT_FILE'):
            from src.engine.deployment import configured_dispatcher
            container_manager = configured_dispatcher(get_session_factory(), self.credentials)
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
        return await self._start_execution(request,context)

    async def RestartExecution(self,request,context):
        await self._authorize_execution(context,request.execution_id)
        user_id,_=await self._principal(context)
        if not 1<=len(request.request_key)<=128:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Restart request key is required')
        async with get_session_factory()() as session:
            source=await session.get(WorkflowExecutionModel,request.execution_id)
            if source.user_id!=user_id:
                await context.abort(grpc.StatusCode.PERMISSION_DENIED,'Only the owner can restart an execution')
            graph=source.graph_json
            key_hash=hashlib.sha256(request.request_key.encode()).hexdigest()
            id=str(uuid.uuid5(uuid.NAMESPACE_URL,json.dumps(['lectify-restart',source.id,user_id,key_hash])))
            if source.state not in ('COMPLETED','FAILED','CANCELLED') and await session.get(WorkflowExecutionModel,id) is None:
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION,'Only terminal executions can be fully restarted')
            nodes=[pb.WorkflowNode(id=node['id'],plugin_id=node['plugin_id'],plugin_version=node.get('plugin_version','0.1.0'),
                parameters_json=json.dumps(node.get('parameters',{})),input_mapping_json=json.dumps(node.get('input_mapping',[])),
                input_bindings=node.get('input_bindings',{}),prompt_id=node.get('prompt_id',''),
                name=node.get('name',''),description=node.get('description','')) for node in graph['nodes']]
            candidate=pb.StartExecutionRequest(execution_id=id,workflow_id=source.workflow_id,user_id=user_id,
                graph=pb.WorkflowGraph(nodes=nodes,edges=[pb.WorkflowEdge(**edge) for edge in graph['edges']]),
                initial_inputs=source.initial_inputs)
        return await self._start_execution(candidate,context,restart_source=request.execution_id,restart_key_hash=key_hash)

    async def _start_execution(self,request,context,*,restart_source=None,restart_key_hash=None):
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
        if (len(initial_inputs) > 128 or any(len(key) > 128 or len(value.encode('utf-8')) > 65536
                for key, value in initial_inputs.items())):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Execution inputs exceed limits')
        for node in nodes_data:
            for mapping in node.get('input_mapping', []):
                source = mapping['source']
                if (not source.startswith('input.') or mapping['transform'] != 'passthrough'
                        or source[len('input.'):] not in initial_inputs):
                    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Required external input is missing or invalid')
        credential = None
        if getattr(self.container_manager,'requires_credentials',False) and self.credentials is None:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION,'Execution credential storage is not configured')
        if self.credentials is not None:
            try:
                token = delegated_metadata(context)[0][1][7:]
                credential = self.credentials.prepare(execution_id,user_id,token,
                    getattr(context.lectify_principal,'access_expires_at',0))
            except (PermissionError,ValueError):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED,'A live user credential is required for background execution')
        async def reuse(saved):
            if saved.user_id != user_id:
                await context.abort(grpc.StatusCode.NOT_FOUND, 'Execution not found')
            if (saved.workflow_id != workflow_id or saved.graph_json != graph_json
                    or saved.initial_inputs != initial_inputs or saved.parent_execution_id!=restart_source
                    or saved.restart_key_hash!=restart_key_hash):
                await context.abort(grpc.StatusCode.ALREADY_EXISTS, 'Execution ID is bound to another request')
            return pb.StartExecutionResponse(execution_id=saved.id,
                workflow_id=saved.workflow_id,parent_execution_id=saved.parent_execution_id or '',
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
                parent_execution_id=restart_source,restart_key_hash=restart_key_hash,
                credentials_required=credential is not None,
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
            if credential is not None:
                session.add(credential)

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
                workflow_id=workflow_id,parent_execution_id=restart_source or '',
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
        if self.credentials is not None:
            async def purge(session):
                await self.credentials.purge(session)
            await run_transaction(factory,purge)
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
            if fence is not None:
                await attempt_history.interrupt(session,execution_id,'INTERRUPTED',before_fence=fence)
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
        operation_started = time.monotonic()
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
            from generated.observability.operations import completion
            completion('workflow','completed',time.monotonic()-operation_started)

        except Exception as e:
            log.error("pipeline_failed", execution_id=execution_id, error=str(e))
            from generated.docker_sandbox import DockerCommandError
            transient=isinstance(e,DockerCommandError) or (isinstance(e,grpc.aio.AioRpcError)
                and e.code() in (grpc.StatusCode.UNAVAILABLE,grpc.StatusCode.DEADLINE_EXCEEDED))
            if transient and ownership is not None and getattr(self.container_manager,'supports_streaming',False) and flags.auto_retry_failed_nodes:
                async def retry(session):
                    if not await guard_execution_write(session,execution_id,ownership): return False
                    execution=await session.get(WorkflowExecutionModel,execution_id)
                    await attempt_history.interrupt(session,execution_id,'INTERRUPTED')
                    node=await session.scalar(select(WorkflowNodeExecutionModel).where(
                        WorkflowNodeExecutionModel.execution_id==execution_id,
                        WorkflowNodeExecutionModel.node_id==getattr(e,'_lectify_failed_node',None)))
                    if node is None or node.automatic_retries>=2: return False
                    node.automatic_retries+=1
                    execution.automatic_retries+=1
                    execution.total_progress=await reset_unfinished(session,execution_id)
                    node.progress_message=f'Повторная попытка {node.automatic_retries}/2 после временной ошибки'
                    dispatch=await session.get(WorkflowDispatchModel,execution_id)
                    revoke(dispatch,'PENDING')
                    dispatch.lease_expires_at=database_epoch(session)+2**node.automatic_retries
                    return True
                try: scheduled=await run_transaction(session_factory,retry)
                except ValueError: scheduled=False
                if scheduled:
                    log.info('workflow_retry_scheduled',execution_id=execution_id)
                    from generated.observability.operations import completion
                    completion('workflow','retry',time.monotonic()-operation_started)
                    return
            async with session_factory() as session:
                if not await guard_execution_write(session, execution_id, ownership):
                    return
                changed = await session.execute(update(WorkflowExecutionModel).where(
                    WorkflowExecutionModel.id == execution_id,
                    WorkflowExecutionModel.state == "RUNNING",
                ).values(state="FAILED", error_message=str(e), finished_at=utc_now()))
                if changed.rowcount == 1:
                    await attempt_history.interrupt(session,execution_id,'INTERRUPTED')
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
            from generated.observability.operations import completion
            completion('workflow','failed',time.monotonic()-operation_started)


    async def _run_stream_nodes(self, execution_id, nodes, dag, initial_inputs, ownership):
        factory = get_session_factory()
        checkpoints = StreamCheckpoints(factory,execution_id,ownership)
        replayed=set()
        measurements_by_node={}
        async def execute_node(node, inputs):
            started = time.monotonic()
            stats = {'input':0,'output':0,'chunks':0}
            measurements_by_node[node['id']]=(stats,started)
            async def counted_inputs():
                async for frame in inputs:
                    stats['input'] += len(frame.payload)
                    yield frame
            if await checkpoints.begin(node['id']):
                replayed.add(node['id'])
                async with aclosing(checkpoints.replay(node['id'],inputs)) as replay:
                    async for frame in replay: yield frame
                return
            async with aclosing(self.container_manager.stream_node(execution_id=execution_id, node=node,
                    inputs=counted_inputs(), ownership=ownership, initial_inputs=initial_inputs)) as output:
                async for frame in output:
                    stats['output'] += len(frame.payload)
                    if stats['output']>1024*1048576 or stats['chunks']>=65536:
                        raise ValueError('Durable node output exceeds storage limit')
                    await checkpoints.append(node['id'],stats['chunks'],frame)
                    stats['chunks'] += 1
                    yield frame
            async def measurements(session):
                if not await guard_execution_write(session, execution_id, ownership):
                    raise RuntimeError('Execution stream lease was lost')
                await session.execute(update(WorkflowNodeExecutionModel).where(
                    WorkflowNodeExecutionModel.execution_id == execution_id,
                    WorkflowNodeExecutionModel.node_id == node['id'],
                ).values(bytes_streamed_in=stats['input'],bytes_streamed_out=stats['output'],
                    chunks_processed=stats['chunks'],execution_time_ms=int((time.monotonic()-started)*1000)))
            await run_transaction(factory,measurements)
        async def run_node(node,inputs):
            try:
                async with aclosing(execute_node(node,inputs)) as outputs:
                    async for frame in outputs: yield frame
            except BaseException as error:
                logs_incomplete=getattr(self.container_manager,'take_incomplete_logs',lambda *a:False)(execution_id,node['id'])
                async def failed(session):
                    if not await guard_execution_write(session,execution_id,ownership): return
                    stats,started=measurements_by_node[node['id']]
                    await attempt_history.finish(session,execution_id,node['id'],
                        'INTERRUPTED' if isinstance(error,asyncio.CancelledError) else 'FAILED',ownership,
                        dict(stats,elapsed=int((time.monotonic()-started)*1000)),type(error).__name__,
                        logs_incomplete=logs_incomplete)
                await run_transaction(factory,failed)
                if isinstance(error,asyncio.CancelledError): raise
                error._lectify_failed_node=node['id']
                raise
        async def complete(node):
            if node['id'] in replayed: return
            async def persist(session):
                if not await guard_execution_write(session, execution_id, ownership):
                    raise RuntimeError('Execution stream lease was lost')
                await session.execute(update(WorkflowNodeExecutionModel).where(
                    WorkflowNodeExecutionModel.execution_id == execution_id,
                    WorkflowNodeExecutionModel.node_id == node['id'],
                    WorkflowNodeExecutionModel.state == 'PROCESSING',
                ).values(state='COMPLETED', progress_percent=100,checkpoint_ready=True))
                stats,started=measurements_by_node[node['id']]
                await attempt_history.finish(session,execution_id,node['id'],'COMPLETED',ownership,
                    dict(stats,elapsed=int((time.monotonic()-started)*1000)),
                    logs_incomplete=getattr(self.container_manager,'take_incomplete_logs',lambda *a:False)(execution_id,node['id']))
                completed = await session.scalar(select(func.count()).select_from(WorkflowNodeExecutionModel).where(
                    WorkflowNodeExecutionModel.execution_id == execution_id,
                    WorkflowNodeExecutionModel.state == 'COMPLETED'))
                await session.execute(update(WorkflowExecutionModel).where(
                    WorkflowExecutionModel.id == execution_id,
                ).values(total_progress=int(100*completed/len(nodes))))
            await run_transaction(factory, persist)
        await run_streaming_graph(execution_id, nodes, dag.edges, run_node,
            on_node_complete=complete, initial_inputs=initial_inputs)

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
            await attempt_history.interrupt(session,request.execution_id,'CANCELLED')
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

        await self._cleanup_execution(request.execution_id)

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
                output_artifacts={k: v['file_id'] if isinstance(v, dict) else str(v)
                    for k, v in (n.output_artifacts or {}).items()},
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

    async def GetExecutionDetails(self,request,context):
        status=await self.GetExecutionStatus(request,context)
        async with get_session_factory()() as session:
            execution=await session.get(WorkflowExecutionModel,request.execution_id)
            nodes=[await execution_details.node_details(session,execution,node['id'],context,size=1)
                for node in execution.graph_json['nodes']]
            return pb.ExecutionDetails(status=status,workflow_id=execution.workflow_id,
                parent_execution_id=execution.parent_execution_id or '',graph_json=json.dumps(execution.graph_json,ensure_ascii=False),
                initial_inputs=execution.initial_inputs,nodes=nodes)

    async def GetNodeDetails(self,request,context):
        await self._authorize_execution(context,request.execution_id)
        size=request.page_size or 20
        if not 1<=size<=100 or not 0<=request.offset<=10000:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Invalid attempt pagination')
        async with get_session_factory()() as session:
            execution=await session.get(WorkflowExecutionModel,request.execution_id)
            return await execution_details.node_details(session,execution,request.node_id,context,size,request.offset)

    async def GetNodeLogs(self,request,context):
        await self._authorize_execution(context,request.execution_id)
        size=request.page_size or 100
        if not 1<=size<=100 or request.after_sequence<0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Invalid log pagination')
        async with get_session_factory()() as session:
            return await execution_details.read_logs(session,request,context,size)

    async def DownloadNodeLog(self,request,context):
        await self._authorize_execution(context,request.execution_id)
        from src.models import NodeEventModel
        async with get_session_factory()() as session:
            attempt=await execution_details.attempt_row(session,request,context)
            cutoff=await session.scalar(select(func.max(NodeEventModel.sequence)).where(NodeEventModel.execution_id==request.execution_id,
                NodeEventModel.node_id==request.node_id,NodeEventModel.fence==attempt.fence,NodeEventModel.kind=='log')) or 0
            truncated=attempt.logs_truncated
        cursor,sequence,total=0,0,0
        buffer=bytearray()
        filename=f'{request.node_id}.attempt-{request.attempt_number}.log'
        while cutoff:
            page_request=pb.NodeLogsRequest(execution_id=request.execution_id,node_id=request.node_id,
                attempt_number=request.attempt_number,after_sequence=cursor)
            async with get_session_factory()() as session:
                page=await execution_details.read_logs(session,page_request,context,100,before_sequence=cutoff)
            for entry in page.entries:
                text=f'[{entry.timestamp}] [{entry.level}] [{entry.stream}] {entry.message}'
                if entry.fields: text+=' '+json.dumps(dict(entry.fields),ensure_ascii=False,sort_keys=True)
                encoded=(text+'\n').encode('utf-8')
                if total+len(encoded)>4194304:
                    truncated=True; cutoff=0; break
                total+=len(encoded); buffer.extend(encoded)
                while len(buffer)>=65536:
                    yield pb.NodeLogChunk(data=bytes(buffer[:65536]),sequence=sequence,filename=filename,truncated=truncated)
                    del buffer[:65536]; sequence+=1
            if not page.has_more: break
            cursor=page.next_sequence
        if truncated: buffer.extend(b'\n[TRUNCATED: log is incomplete or exceeds configured limits]\n')
        while len(buffer)>65536:
            yield pb.NodeLogChunk(data=bytes(buffer[:65536]),sequence=sequence,filename=filename,truncated=truncated)
            del buffer[:65536]; sequence+=1
        if buffer:
            yield pb.NodeLogChunk(data=bytes(buffer),sequence=sequence,filename=filename,truncated=truncated); sequence+=1
        yield pb.NodeLogChunk(sequence=sequence,is_last=True,filename=filename,truncated=truncated)

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
        previous_task=self._execution_tasks.get(request.execution_id)
        async def persist(session):
            execution,dispatch=await locked_execution(session,request.execution_id)
            if execution.state=='PAUSED': return
            if execution.state!='RUNNING': raise ValueError('Only running executions can be paused')
            execution.state='PAUSED'
            await attempt_history.interrupt(session,request.execution_id,'PAUSED')
            revoke(dispatch,'PAUSED')
            await session.execute(update(WorkflowNodeExecutionModel).where(
                WorkflowNodeExecutionModel.execution_id==request.execution_id,
                WorkflowNodeExecutionModel.state.in_(('PROVISIONING','BUFFERING','PROCESSING')),
            ).values(state='PENDING',progress_message='Исполнение приостановлено'))
        await self._lifecycle_transaction(persist,context)
        await self._stop_local_execution(previous_task)
        await self._cleanup_execution(request.execution_id)
        return pb.PauseExecutionResponse(success=True,state=pb.EXECUTION_STATE_PAUSED)

    async def ResumeExecution(
        self,
        request: pb.ResumeExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.ResumeExecutionResponse:
        await self._authorize_execution(context, request.execution_id)
        await self._resume_or_retry(request.execution_id,context)
        return pb.ResumeExecutionResponse(success=True,state=pb.EXECUTION_STATE_RUNNING)

    async def RetryNode(
        self,
        request: pb.RetryNodeRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.RetryNodeResponse:
        await self._authorize_execution(context, request.execution_id)
        if not request.node_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Node ID is required')
        await self._resume_or_retry(request.execution_id,context,node_id=request.node_id)
        return pb.RetryNodeResponse(success=True,state=pb.NODE_STATE_PENDING)

    async def _lifecycle_transaction(self,transaction,context):
        try:
            return await run_transaction(get_session_factory(),transaction)
        except LookupError as error:
            await context.abort(grpc.StatusCode.NOT_FOUND,str(error))
        except ValueError as error:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION,str(error))

    async def _stop_local_execution(self,task):
        if task is not None and task is not asyncio.current_task():
            if not task.done() and not task.cancelling(): task.cancel()
            await asyncio.shield(asyncio.gather(task,return_exceptions=True))

    async def _cleanup_execution(self,execution_id):
        from src.engine.launch import cleanup_created_containers
        workers=getattr(self.container_manager,'workers',None)
        if workers is not None:
            for _,sandbox in workers.items():
                try:
                    while await cleanup_created_containers(get_session_factory(),sandbox,execution_id=execution_id)==100:
                        pass
                except (RuntimeError,OSError,TimeoutError):
                    log.warning('execution_cleanup_deferred',execution_id=execution_id)

    async def _resume_or_retry(self,execution_id,context,node_id=None):
        user_id,_=await self._principal(context)
        previous_task=self._execution_tasks.get(execution_id)
        async def persist(session):
            execution,dispatch=await locked_execution(session,execution_id)
            if node_id is None and execution.state=='RUNNING': return False
            expected='FAILED' if node_id is not None else 'PAUSED'
            if execution.state!=expected:
                raise ValueError('Execution must be '+expected.lower())
            invalidated=descendants(execution.graph_json,node_id) if node_id is not None else ()
            if self.credentials is not None:
                # Resuming with someone else's delegated credential would change
                # file/prompt ownership checks inside plugin assignments.
                if user_id!=execution.user_id:
                    await context.abort(grpc.StatusCode.PERMISSION_DENIED,'Only the execution owner can renew its credential')
                try:
                    token=delegated_metadata(context)[0][1][7:]
                    credential=self.credentials.prepare(execution_id,user_id,token,
                        getattr(context.lectify_principal,'access_expires_at',0))
                except (PermissionError,ValueError):
                    await context.abort(grpc.StatusCode.UNAUTHENTICATED,'A live user credential is required')
                await session.merge(credential)
            execution.total_progress=await reset_unfinished(session,execution_id,invalidated=invalidated,reset_retries=node_id is not None)
            execution.state,execution.error_message,execution.finished_at='RUNNING',None,None
            if node_id is not None: execution.automatic_retries=0
            revoke(dispatch,'PENDING')
            return True
        changed=await self._lifecycle_transaction(persist,context)
        if changed:
            await self._stop_local_execution(previous_task)
            await self._cleanup_execution(execution_id)
            await self.dispatch_pending()

    async def RegisterPluginManifest(
        self,
        request: pb.RegisterPluginManifestRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.RegisterPluginManifestResponse:
        _, admin = await self._principal(context)
        if not admin:
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Plugin registration requires administrator access')
        try:
            if (not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',request.plugin_id)
                    or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,32}',request.version)):
                raise ValueError()
            manifest, canonical = parse_plugin_manifest(request.manifest_yaml)
            plugin = manifest['plugin']
            if plugin['name'] != request.plugin_id or plugin['version'] != request.version:
                raise ValueError()
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Invalid plugin manifest or version identity')
        session_factory = get_session_factory()
        async def persist(session):
            async def verify(existing):
                try:
                    _, saved = parse_plugin_manifest(existing.manifest_yaml)
                except ValueError:
                    saved = None
                if saved != canonical:
                    await context.abort(grpc.StatusCode.ALREADY_EXISTS,'Plugin version is immutable')
            existing = await session.get(PluginRegistryModel,(request.plugin_id,request.version))
            if existing is not None:
                await verify(existing)
                return
            model = PluginRegistryModel(
                id=request.plugin_id,
                version=request.version,
                name=request.plugin_id,
                manifest_yaml=canonical,category=plugin['category'],description=plugin['description'],
                active=plugin['active'],
            )
            session.add(model)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                existing = await session.get(PluginRegistryModel,(request.plugin_id,request.version))
                if existing is None:
                    raise
                await verify(existing)
        await run_transaction(session_factory,persist)

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

    async def GetPluginManifest(self, request, context):
        await self._principal(context)
        if not request.plugin_id or not request.version or len(request.plugin_id) > 128 or len(request.version) > 64:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Pinned plugin identity required')
        async with get_session_factory()() as session:
            row = await session.get(PluginRegistryModel, (request.plugin_id, request.version))
            if row is None or not row.active:
                await context.abort(grpc.StatusCode.NOT_FOUND, 'Active plugin version not found')
            _, canonical = parse_plugin_manifest(row.manifest_yaml)
            return pb.GetPluginManifestResponse(manifest_json=canonical)

    async def ListExecutions(self, request, context):
        user_id, _ = await self._principal(context)
        size = request.page_size or 20
        if not 1 <= size <= 100 or not 0 <= request.offset <= 10000:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid execution pagination')
        async with get_session_factory()() as session:
            rows = list((await session.scalars(select(WorkflowExecutionModel).where(
                WorkflowExecutionModel.user_id == user_id).order_by(
                WorkflowExecutionModel.created_at.desc(), WorkflowExecutionModel.id.desc())
                .offset(request.offset).limit(size+1))).all())
        return pb.ListExecutionsResponse(has_more=len(rows)>size, executions=[pb.ExecutionSummary(
            execution_id=row.id,workflow_id=row.workflow_id,state='EXECUTION_STATE_'+row.state,
            parent_execution_id=row.parent_execution_id or '',
            total_progress_percent=row.total_progress,started_at=epoch(row.created_at),
            finished_at=epoch(row.finished_at) if row.finished_at else 0)
            for row in rows[:size]])
