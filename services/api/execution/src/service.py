"""Execution policy over workflow snapshots; RPC infrastructure is generated."""
import asyncio
from contextlib import asynccontextmanager
import json
import re
import uuid

import grpc

from generated.grpc_server.grpc_app import ExecutionServiceBase
from generated.grpc_client.grpc_clients import GrpcClients
from generated.user_auth.client import delegated_metadata
from generated.protos.server import index_pb2 as pb
from generated.protos.clients.api_workflow import index_pb2 as workflow_pb, index_pb2_grpc as workflow_rpc
from generated.protos.clients.orchestrator import index_pb2 as orch_pb, index_pb2_grpc as orch_rpc


class ExecutionServiceImpl(ExecutionServiceBase):
    def __init__(self, clients_factory=None, timeout=30):
        if type(timeout) not in (int,float) or not 0 < timeout <= 300:
            raise ValueError('Execution backend deadline must be bounded')
        self._clients_factory = clients_factory
        self.timeout = timeout

    @asynccontextmanager
    async def _backends(self, context):
        principal = getattr(context,'lectify_principal',None)
        user = getattr(principal,'user_id',None)
        if not isinstance(user,str) or not user or len(user)>64:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED,'Verified user identity required')
        try:
            metadata = delegated_metadata(context)
        except PermissionError:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED,'Delegated user credential required')
        clients = self._clients_factory() if self._clients_factory else GrpcClients(source_service='api_execution')
        try:
            async with asyncio.timeout(self.timeout):
                yield clients, metadata, user
        except grpc.aio.AioRpcError as error:
            await context.abort(error.code(),'Execution backend request failed')
        except TimeoutError:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED,'Execution backend deadline exceeded')
        except (ValueError,TypeError):
            await context.abort(grpc.StatusCode.UNAVAILABLE,'Invalid execution backend response')
        finally:
            await clients.close_all()

    async def _id(self, value, context):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}',value):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Invalid resource identifier')

    async def StartWorkflow(self, request, context):
        await self._id(request.workflow_id,context)
        if not 1 <= len(request.request_key) <=128 or request.expected_version <=0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Request key and positive workflow version required')
        if (len(request.initial_inputs)>128 or any(len(key)>128 or len(value.encode())>65536
                for key,value in request.initial_inputs.items())):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Execution inputs exceed limits')
        async with self._backends(context) as (clients,metadata,user):
            workflow = workflow_rpc.WorkflowServiceStub(clients.channel('api_workflow'))
            snapshot = await workflow.CreateSnapshot(workflow_pb.CreateSnapshotRequest(workflow_id=request.workflow_id,
                expected_version=request.expected_version,request_key=request.request_key),metadata=metadata,timeout=self.timeout)
            if (snapshot.created_by != user or snapshot.workflow_id != request.workflow_id
                    or snapshot.workflow_version != request.expected_version):
                await context.abort(grpc.StatusCode.UNAVAILABLE,'Invalid workflow snapshot scope')
            try:
                if str(uuid.UUID(snapshot.id)) != snapshot.id or not re.fullmatch(r'[a-f0-9]{64}',snapshot.content_hash):
                    raise ValueError()
            except ValueError:
                await context.abort(grpc.StatusCode.UNAVAILABLE,'Invalid workflow snapshot identity')
            execution_id = str(uuid.uuid5(uuid.NAMESPACE_URL,json.dumps(['lectify-execution',user,snapshot.id])))
            graph = orch_pb.WorkflowGraph(nodes=[orch_pb.WorkflowNode(id=node.id,plugin_id=node.plugin_id,
                plugin_version=node.plugin_version,parameters_json=node.parameters_json,prompt_id=node.prompt_id,
                input_mapping_json=json.dumps([dict(target_field=item.target_field,source=item.source,transform=item.transform)
                    for item in node.input_mapping],ensure_ascii=False)) for node in snapshot.graph.nodes],
                edges=[orch_pb.WorkflowEdge(from_node_id=edge.from_node_id,from_output=edge.from_output,
                    to_node_id=edge.to_node_id,to_input=edge.to_input) for edge in snapshot.graph.edges])
            orchestrator = orch_rpc.OrchestratorServiceStub(clients.channel('orchestrator'))
            result = await orchestrator.StartExecution(orch_pb.StartExecutionRequest(workflow_id=snapshot.id,
                execution_id=execution_id,user_id=user,graph=graph,initial_inputs=request.initial_inputs),
                metadata=metadata,timeout=self.timeout)
            if result.execution_id != execution_id:
                await context.abort(grpc.StatusCode.UNAVAILABLE,'Invalid execution response scope')
            return pb.StartWorkflowResponse(execution_id=result.execution_id,snapshot_id=snapshot.id,
                snapshot_hash=snapshot.content_hash,state=orch_pb.ExecutionState.Name(result.state),started_at=result.started_at)

    async def GetStatus(self, request, context):
        await self._id(request.execution_id,context)
        async with self._backends(context) as (clients,metadata,_):
            stub = orch_rpc.OrchestratorServiceStub(clients.channel('orchestrator'))
            result = await stub.GetExecutionStatus(orch_pb.GetExecutionStatusRequest(execution_id=request.execution_id),
                metadata=metadata,timeout=self.timeout)
            if result.execution_id != request.execution_id:
                await context.abort(grpc.StatusCode.UNAVAILABLE,'Invalid execution response scope')
            return pb.ExecutionStatus(execution_id=result.execution_id,state=orch_pb.ExecutionState.Name(result.state),
                total_progress_percent=result.total_progress_percent,started_at=result.started_at,
                finished_at=result.finished_at,error_message=result.error_message,nodes=[pb.NodeStatus(
                    node_id=node.node_id,plugin_id=node.plugin_id,state=orch_pb.NodeState.Name(node.state),
                    progress_percent=node.progress_percent,progress_message=node.progress_message,
                    bytes_streamed_in=node.bytes_streamed_in,bytes_streamed_out=node.bytes_streamed_out,
                    chunks_processed=node.chunks_processed,execution_time_ms=node.execution_time_ms,
                    error_message=node.error_message,output_artifacts=node.output_artifacts) for node in result.nodes])

    async def Cancel(self, request, context):
        await self._id(request.execution_id,context)
        if len(request.reason)>4096:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Cancellation reason exceeds limit')
        async with self._backends(context) as (clients,metadata,_):
            stub = orch_rpc.OrchestratorServiceStub(clients.channel('orchestrator'))
            result = await stub.CancelExecution(orch_pb.CancelExecutionRequest(execution_id=request.execution_id,
                reason=request.reason),metadata=metadata,timeout=self.timeout)
            return pb.CancelResponse(success=result.success,state=orch_pb.ExecutionState.Name(result.state))

    async def StreamEvents(self, request, context):
        await self._id(request.execution_id,context)
        if request.after_sequence<0:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Event cursor must be nonnegative')
        async with self._backends(context) as (clients,metadata,_):
            stub = orch_rpc.OrchestratorServiceStub(clients.channel('orchestrator'))
            call = stub.StreamExecutionEvents(orch_pb.StreamExecutionEventsRequest(execution_id=request.execution_id,
                after_sequence=request.after_sequence),metadata=metadata,timeout=self.timeout)
            try:
                cursor = request.after_sequence
                async for event in call:
                    if (event.execution_id != request.execution_id or event.sequence < 0
                            or event.sequence and event.sequence <= cursor):
                        await context.abort(grpc.StatusCode.UNAVAILABLE,'Invalid execution event scope or cursor')
                    yield pb.ExecutionEvent(execution_id=event.execution_id,node_id=event.node_id,
                        event_type=orch_pb.EventType.Name(event.event_type),timestamp=event.timestamp,
                        message=event.message,progress_percent=event.progress_percent,metadata=event.metadata,sequence=event.sequence)
                    if event.sequence:
                        cursor = event.sequence
            finally:
                call.cancel()
