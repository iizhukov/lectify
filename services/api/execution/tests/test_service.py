import asyncio
import json
from types import SimpleNamespace

import grpc
import pytest

from generated.testing.context import MockServicerContext, MockRpcError
from generated.protos.server import index_pb2 as pb
import src.service as module


def context():
    value = MockServicerContext(metadata={'x-user-authorization':'Bearer delegated-test-token','x-user-id':'spoofed'})
    value.lectify_principal = SimpleNamespace(user_id='owner',is_admin=False)
    return value


def request():
    return pb.StartWorkflowRequest(workflow_id='workflow',expected_version=2,request_key='request',initial_inputs={'file_id':'file'})


@pytest.fixture
def dependencies(monkeypatch):
    created, starts, calls = [], [], []
    snapshot = module.workflow_pb.WorkflowSnapshot(id='f9356b4b-b028-4462-821c-1c8d8da4d05c',
        workflow_id='workflow',workflow_version=2,created_by='owner',content_hash='a'*64,
        graph=module.workflow_pb.WorkflowGraph(nodes=[module.workflow_pb.GraphNode(id='node',plugin_id='plugin',
            parameters_json='{"enabled":true,"values":[1,2]}',prompt_id='prompt')]))
    class Workflow:
        delayed = False
        async def CreateSnapshot(self, req, **options):
            calls.append(options)
            if self.delayed:
                await asyncio.sleep(1)
            return snapshot
    class Stream:
        cancelled = False
        def __aiter__(self):
            async def iterate():
                yield module.orch_pb.ExecutionEvent(execution_id='execution',node_id='node',sequence=7,
                    event_type=module.orch_pb.EVENT_TYPE_NODE_PROGRESS,message='progress',progress_percent=50)
            return iterate()
        def cancel(self): self.cancelled = True
    stream = Stream()
    class Orchestrator:
        async def RestartExecution(self,req,**options):
            calls.append(options)
            assert req.request_key=='restart-key'
            return module.orch_pb.StartExecutionResponse(execution_id='child',parent_execution_id=req.execution_id,
                workflow_id=snapshot.id,state=module.orch_pb.EXECUTION_STATE_RUNNING,started_at=123)
        async def GetExecutionDetails(self,req,**options):
            calls.append(options)
            return module.orch_pb.ExecutionDetails(status=module.orch_pb.GetExecutionStatusResponse(execution_id=req.execution_id,
                state=module.orch_pb.EXECUTION_STATE_COMPLETED),parent_execution_id='parent',graph_json='{"nodes":[]}',
                initial_inputs={'file':'owned'})
        async def GetNodeDetails(self,req,**options):
            calls.append(options)
            return module.orch_pb.NodeDetails(node_id=req.node_id,plugin_id='plugin',parameters_json='{"value":1}',
                attempts=[module.orch_pb.NodeAttempt(id='attempt',number=2,state='FAILED',log_bytes=42)])
        async def GetNodeLogs(self,req,**options):
            calls.append(options)
            assert req.attempt_number==2 and req.after_sequence==10
            return module.orch_pb.NodeLogsResponse(entries=[module.orch_pb.NodeLogEntry(sequence=11,level='ERROR',message='diagnostic')],next_sequence=11)
        async def StartExecution(self, req, **options):
            starts.append(req)
            calls.append(options)
            return module.orch_pb.StartExecutionResponse(execution_id=req.execution_id,
                state=module.orch_pb.EXECUTION_STATE_RUNNING,started_at=123)
        async def GetExecutionStatus(self, req, **options):
            calls.append(options)
            return module.orch_pb.GetExecutionStatusResponse(execution_id=req.execution_id,
                state=module.orch_pb.EXECUTION_STATE_RUNNING,nodes=[module.orch_pb.NodeExecutionStatus(
                    node_id='node',plugin_id='plugin',state=module.orch_pb.NODE_STATE_PROCESSING,progress_percent=50)])
        async def CancelExecution(self, req, **options):
            calls.append(options)
            return module.orch_pb.CancelExecutionResponse(success=True,state=module.orch_pb.EXECUTION_STATE_CANCELLED)
        async def PauseExecution(self,req,**options):
            calls.append(options)
            return module.orch_pb.PauseExecutionResponse(success=True,state=module.orch_pb.EXECUTION_STATE_PAUSED)
        async def ResumeExecution(self,req,**options):
            calls.append(options)
            return module.orch_pb.ResumeExecutionResponse(success=True,state=module.orch_pb.EXECUTION_STATE_RUNNING)
        async def RetryNode(self,req,**options):
            calls.append(options)
            assert req.node_id=='node'
            return module.orch_pb.RetryNodeResponse(success=True,state=module.orch_pb.NODE_STATE_PENDING)
        def StreamExecutionEvents(self, req, **options):
            assert req.after_sequence == 6
            calls.append(options)
            return stream
    workflow, orchestrator = Workflow(), Orchestrator()
    class Clients:
        def __init__(self):
            self.closed = False
            created.append(self)
        def channel(self, service): return service
        async def close_all(self): self.closed = True
    monkeypatch.setattr(module.workflow_rpc,'WorkflowServiceStub',lambda channel:workflow)
    monkeypatch.setattr(module.orch_rpc,'OrchestratorServiceStub',lambda channel:orchestrator)
    return SimpleNamespace(factory=Clients,created=created,starts=starts,calls=calls,
        snapshot=snapshot,workflow=workflow,stream=stream,orchestrator=orchestrator)


@pytest.mark.asyncio
async def test_restart_details_and_attempt_logs_forward_scoped_metadata(dependencies):
    service=module.ExecutionServiceImpl(dependencies.factory)
    restarted=await service.Restart(pb.RestartRequest(execution_id='original',request_key='restart-key'),context())
    assert restarted.execution_id=='child' and restarted.parent_execution_id=='original'
    assert restarted.snapshot_id==dependencies.snapshot.id
    details=await service.GetDetails(pb.ExecutionRequest(execution_id='child'),context())
    assert details.status.state=='EXECUTION_STATE_COMPLETED' and details.initial_inputs=={'file':'owned'}
    node=await service.GetNodeDetails(pb.NodeDetailsRequest(execution_id='child',node_id='node',page_size=10),context())
    assert node.attempts[0].number==2 and node.attempts[0].log_bytes==42
    logs=await service.GetNodeLogs(pb.NodeLogsRequest(execution_id='child',node_id='node',attempt_number=2,after_sequence=10),context())
    assert logs.entries[0].message=='diagnostic' and logs.next_sequence==11
    assert all(client.closed for client in dependencies.created)
    assert all(call['metadata']==(('x-user-authorization','Bearer delegated-test-token'),) for call in dependencies.calls)


@pytest.mark.asyncio
async def test_node_log_download_validates_eof_and_closes_transport(dependencies,monkeypatch):
    class LogStream:
        cancelled=False
        terminal=True
        def __aiter__(self):
            async def frames():
                yield module.orch_pb.NodeLogChunk(data=b'diagnostic',filename='node.attempt-1.log')
                if self.terminal: yield module.orch_pb.NodeLogChunk(sequence=1,is_last=True,filename='node.attempt-1.log')
            return frames()
        def cancel(self): self.cancelled=True
    stream=LogStream()
    monkeypatch.setattr(dependencies.orchestrator,'DownloadNodeLog',lambda *a,**k:stream,raising=False)
    service=module.ExecutionServiceImpl(dependencies.factory)
    request=pb.NodeLogRequest(execution_id='execution',node_id='node',attempt_number=1)
    chunks=[chunk async for chunk in service.DownloadNodeLog(request,context())]
    assert chunks[-1].is_last and b''.join(chunk.data for chunk in chunks)==b'diagnostic' and stream.cancelled
    stream.cancelled=False; stream.terminal=False
    with pytest.raises(MockRpcError) as error:
        _=[chunk async for chunk in service.DownloadNodeLog(request,context())]
    assert error.value.code()==grpc.StatusCode.DATA_LOSS and stream.cancelled
    assert all(client.closed for client in dependencies.created)


@pytest.mark.asyncio
async def test_snapshot_start_and_control_forward_only_verified_user_credential(dependencies):
    deps = dependencies
    service = module.ExecutionServiceImpl(deps.factory)
    first = await service.StartWorkflow(request(),context())
    second = await service.StartWorkflow(request(),context())
    assert first.execution_id == second.execution_id
    assert first.snapshot_id == deps.snapshot.id and first.state == 'EXECUTION_STATE_RUNNING'
    assert len(deps.starts) == 2 and deps.starts[0].execution_id == deps.starts[1].execution_id
    assert deps.starts[0].user_id == 'owner' and deps.starts[0].workflow_id == deps.snapshot.id
    assert json.loads(deps.starts[0].graph.nodes[0].parameters_json) == {'enabled':True,'values':[1,2]}
    assert deps.starts[0].graph.nodes[0].prompt_id == 'prompt'
    status = await service.GetStatus(pb.ExecutionRequest(execution_id='execution'),context())
    assert status.nodes[0].state == 'NODE_STATE_PROCESSING'
    cancelled = await service.Cancel(pb.CancelRequest(execution_id='execution'),context())
    assert cancelled.success and cancelled.state == 'EXECUTION_STATE_CANCELLED'
    assert (await service.Pause(pb.ExecutionRequest(execution_id='execution'),context())).state=='EXECUTION_STATE_PAUSED'
    assert (await service.Resume(pb.ExecutionRequest(execution_id='execution'),context())).state=='EXECUTION_STATE_RUNNING'
    assert (await service.RetryNode(pb.RetryNodeRequest(execution_id='execution',node_id='node'),context())).state=='NODE_STATE_PENDING'
    events = [item async for item in service.StreamEvents(pb.EventRequest(execution_id='execution',after_sequence=6),context())]
    assert events[0].sequence == 7 and deps.stream.cancelled
    assert all(client.closed for client in deps.created)
    assert all(options['metadata'] == (('x-user-authorization','Bearer delegated-test-token'),) for options in deps.calls)


@pytest.mark.asyncio
async def test_foreign_snapshot_never_starts_execution(dependencies):
    dependencies.snapshot.created_by = 'another-user'
    with pytest.raises(MockRpcError) as error:
        await module.ExecutionServiceImpl(dependencies.factory).StartWorkflow(request(),context())
    assert error.value.code() == grpc.StatusCode.UNAVAILABLE
    assert not dependencies.starts and all(client.closed for client in dependencies.created)


@pytest.mark.asyncio
async def test_backend_deadline_closes_clients_and_does_not_start(dependencies):
    dependencies.workflow.delayed = True
    with pytest.raises(MockRpcError) as error:
        await module.ExecutionServiceImpl(dependencies.factory,timeout=0.01).StartWorkflow(request(),context())
    assert error.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
    assert not dependencies.starts and all(client.closed for client in dependencies.created)


@pytest.mark.asyncio
async def test_missing_verified_identity_is_rejected_before_clients_open(dependencies):
    with pytest.raises(MockRpcError) as error:
        await module.ExecutionServiceImpl(dependencies.factory).StartWorkflow(request(),MockServicerContext())
    assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED and not dependencies.created
