import pytest
import grpc
import asyncio
from generated.protos.server import index_pb2 as pb
from src.service import OrchestratorServiceImpl
from src.engine.dag import WorkflowDAG, DAGValidationError
from src.engine.stream_router import StreamRouter, StreamChunkData


class WaitingRunner:
    def __init__(self):
        self.started = asyncio.Event()

    async def start_plugin_node(self, **kwargs):
        self.started.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_cancel_atomically_updates_unfinished_nodes_and_preserves_completed(test_session, mock_context):
    from sqlalchemy import select
    from src.models import WorkflowExecutionModel, WorkflowNodeExecutionModel
    execution = WorkflowExecutionModel(id='cancel-node-states', workflow_id='workflow', user_id='user_1', state='RUNNING')
    test_session.add(execution)
    await test_session.flush()
    states = ('PENDING','PROVISIONING','BUFFERING','PROCESSING','COMPLETED','FAILED')
    test_session.add_all([WorkflowNodeExecutionModel(execution_id=execution.id,node_id=state,
        plugin_id='plugin',state=state,output_artifacts={'saved':'file'} if state=='COMPLETED' else {}) for state in states])
    await test_session.commit()
    service = OrchestratorServiceImpl()
    for _ in range(2):
        result = await service.CancelExecution(pb.CancelExecutionRequest(execution_id=execution.id,reason='stop'), mock_context)
        assert result.success
    await test_session.refresh(execution)
    assert execution.state == 'CANCELLED'
    rows = list(await test_session.scalars(select(WorkflowNodeExecutionModel).where(
        WorkflowNodeExecutionModel.execution_id == execution.id)))
    for row in rows:
        if row.node_id in ('COMPLETED','FAILED'):
            assert row.state == row.node_id
        else:
            assert row.state == 'CANCELLED' and row.error_message == 'stop'
        if row.node_id == 'COMPLETED':
            assert row.output_artifacts == {'saved':'file'}


@pytest.mark.asyncio
async def test_dag_topological_sort():
    nodes = [
        {"id": "node_input", "plugin_id": "input_streamer"},
        {"id": "node_stt", "plugin_id": "speech_to_text"},
        {"id": "node_llm", "plugin_id": "llm_transform"},
        {"id": "node_sink", "plugin_id": "text_to_md"},
    ]
    edges = [
        {"from_node_id": "node_input", "from_output": "data_stream", "to_node_id": "node_stt", "to_input": "audio_chunk"},
        {"from_node_id": "node_stt", "from_output": "transcript_stream", "to_node_id": "node_llm", "to_input": "text_stream"},
        {"from_node_id": "node_llm", "from_output": "transformed_stream", "to_node_id": "node_sink", "to_input": "text_stream"},
    ]

    dag = WorkflowDAG(nodes=nodes, edges=edges)
    sorted_nodes = dag.topological_sort()

    node_ids = [n["id"] for n in sorted_nodes]
    assert node_ids == ["node_input", "node_stt", "node_llm", "node_sink"]


@pytest.mark.asyncio
async def test_dag_cycle_detection():
    nodes = [
        {"id": "node_a", "plugin_id": "plugin_a"},
        {"id": "node_b", "plugin_id": "plugin_b"},
    ]
    edges = [
        {"from_node_id": "node_a", "from_output": "out", "to_node_id": "node_b", "to_input": "in"},
        {"from_node_id": "node_b", "from_output": "out", "to_node_id": "node_a", "to_input": "in"},
    ]

    dag = WorkflowDAG(nodes=nodes, edges=edges)
    with pytest.raises(DAGValidationError):
        dag.topological_sort()


@pytest.mark.asyncio
async def test_stream_router_buffering():
    router = StreamRouter(execution_id="test_exec_1")
    channel = router.get_or_create_channel(from_node_id="node_a", output_name="out_stream")
    sub_queue = channel.subscribe()

    chunk1 = StreamChunkData(stream_name="out_stream", payload=b"hello ")
    chunk2 = StreamChunkData(stream_name="out_stream", payload=b"world", is_last=True)

    await channel.publish(chunk1)
    await channel.publish(chunk2)

    received1 = await sub_queue.get()
    received2 = await sub_queue.get()

    assert received1.payload == b"hello "
    assert received2.payload == b"world"
    assert received2.is_last is True


@pytest.mark.asyncio
async def test_orchestrator_start_and_get_status(test_session, mock_context):
    runner = WaitingRunner()
    service = OrchestratorServiceImpl(container_manager=runner)

    graph = pb.WorkflowGraph(
        nodes=[
            pb.WorkflowNode(id="node_stt", plugin_id="speech_to_text", parameters={"model": "whisper-1"}),
            pb.WorkflowNode(id="node_llm", plugin_id="llm_transform", parameters={"model": "gpt-4o"}),
        ],
        edges=[
            pb.WorkflowEdge(from_node_id="node_stt", from_output="transcript_stream", to_node_id="node_llm", to_input="text_stream"),
        ],
    )

    req = pb.StartExecutionRequest(
        workflow_id="wf_123",
        graph=graph,
        initial_inputs={"file_id": "file_abc"},
        user_id="user_1",
    )

    res = await service.StartExecution(req, mock_context)
    assert res.execution_id != ""
    assert res.state == pb.EXECUTION_STATE_RUNNING
    await asyncio.wait_for(runner.started.wait(), 2)

    status_req = pb.GetExecutionStatusRequest(execution_id=res.execution_id)
    status_res = await service.GetExecutionStatus(status_req, mock_context)

    assert status_res.execution_id == res.execution_id
    assert len(status_res.nodes) == 2
    await service.CancelExecution(pb.CancelExecutionRequest(execution_id=res.execution_id), mock_context)
    assert not service._execution_tasks


@pytest.mark.asyncio
async def test_orchestrator_cancel_execution(test_session, mock_context):
    runner = WaitingRunner()
    service = OrchestratorServiceImpl(container_manager=runner)

    graph = pb.WorkflowGraph(
        nodes=[pb.WorkflowNode(id="node_single", plugin_id="speech_to_text")],
        edges=[],
    )
    start_req = pb.StartExecutionRequest(workflow_id="wf_cancel", graph=graph)
    start_res = await service.StartExecution(start_req, mock_context)
    await asyncio.wait_for(runner.started.wait(), 2)

    cancel_req = pb.CancelExecutionRequest(execution_id=start_res.execution_id, reason="User stop")
    cancel_res = await service.CancelExecution(cancel_req, mock_context)

    assert cancel_res.success is True
    assert cancel_res.state == pb.EXECUTION_STATE_CANCELLED


@pytest.mark.asyncio
@pytest.mark.parametrize('terminal', ['CANCELLED', 'FAILED', 'COMPLETED'])
async def test_late_worker_cannot_overwrite_terminal_execution(test_session, terminal):
    from unittest.mock import AsyncMock
    from src.models import WorkflowExecutionModel
    row = WorkflowExecutionModel(id='terminal-worker', workflow_id='workflow', state=terminal)
    test_session.add(row)
    await test_session.commit()
    service = OrchestratorServiceImpl()
    service._broadcast_event = AsyncMock()
    await service._run_execution_pipeline(row.id, [], None, {})
    await test_session.refresh(row)
    assert row.state == terminal
    service._broadcast_event.assert_not_called()


@pytest.mark.asyncio
async def test_late_worker_failure_does_not_replace_cancellation(test_session):
    from unittest.mock import AsyncMock
    from src.models import WorkflowExecutionModel
    row = WorkflowExecutionModel(id='cancel-before-failure', workflow_id='workflow', state='RUNNING')
    test_session.add(row)
    await test_session.commit()
    service = OrchestratorServiceImpl()
    async def cancelled_worker(**kwargs):
        row.state = 'CANCELLED'
        await test_session.commit()
        raise RuntimeError('worker failed')
    service.container_manager.start_plugin_node = cancelled_worker
    service._broadcast_event = AsyncMock()
    await service._run_execution_pipeline(row.id, [{'id': 'node', 'plugin_id': 'plugin'}], None, {})
    await test_session.refresh(row)
    assert row.state == 'CANCELLED'
    assert row.error_message is None
    service._broadcast_event.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_cancel_is_idempotent(test_session, mock_context):
    from src.models import WorkflowExecutionModel
    row = WorkflowExecutionModel(id='cancel-again', workflow_id='workflow', state='CANCELLED')
    test_session.add(row)
    await test_session.commit()
    response = await OrchestratorServiceImpl().CancelExecution(
        pb.CancelExecutionRequest(execution_id=row.id), mock_context,
    )
    assert response.success
    assert response.state == pb.EXECUTION_STATE_CANCELLED


@pytest.mark.asyncio
async def test_repeated_cancel_also_cleans_local_router(test_session, mock_context):
    from src.models import WorkflowExecutionModel
    from src.engine.stream_router import StreamClosedError
    row = WorkflowExecutionModel(id='cancel-cleanup-retry', workflow_id='workflow', state='CANCELLED')
    test_session.add(row)
    await test_session.commit()
    service = OrchestratorServiceImpl()
    router = StreamRouter(execution_id=row.id)
    service._active_routers[row.id] = router
    response = await service.CancelExecution(pb.CancelExecutionRequest(execution_id=row.id), mock_context)
    assert response.success
    assert row.id not in service._active_routers
    with pytest.raises(StreamClosedError):
        router.get_or_create_channel('node', 'output')


@pytest.mark.asyncio
async def test_concurrent_cancel_is_idempotent(test_session, mock_context, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from sqlalchemy.sql.selectable import Select
    import src.service as service_module
    from src.models import WorkflowExecutionModel
    row = WorkflowExecutionModel(id='cancel-concurrently', workflow_id='workflow', state='RUNNING')
    test_session.add(row)
    await test_session.commit()
    factory = service_module.get_session_factory()
    both_read = asyncio.Event()
    reads = 0

    @asynccontextmanager
    async def synchronized_session():
        async with factory() as session:
            execute = session.execute
            async def synchronized_execute(statement, *args, **kwargs):
                nonlocal reads
                result = await execute(statement, *args, **kwargs)
                if isinstance(statement, Select) and any(
                        item.get('name') == 'WorkflowExecutionModel' for item in statement.column_descriptions):
                    reads += 1
                    if reads <= 2:
                        if reads == 2:
                            both_read.set()
                        await asyncio.wait_for(both_read.wait(), 2)
                return result
            session.execute = synchronized_execute
            yield session

    monkeypatch.setattr(service_module, 'get_session_factory', lambda: synchronized_session)
    service = OrchestratorServiceImpl()
    request = pb.CancelExecutionRequest(execution_id=row.id)
    responses = await asyncio.wait_for(asyncio.gather(
        service.CancelExecution(request, type(mock_context)()),
        service.CancelExecution(request, type(mock_context)()),
    ), 3)
    assert all(response.success for response in responses)
    await test_session.refresh(row)
    assert row.state == 'CANCELLED'


@pytest.mark.asyncio
async def test_cancel_stops_running_local_worker(test_session, mock_context):
    import asyncio
    from src.models import WorkflowExecutionModel
    started = asyncio.Event()
    stopped = asyncio.Event()
    service = OrchestratorServiceImpl()

    async def blocked_worker(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    service.container_manager.start_plugin_node = blocked_worker
    response = await service.StartExecution(pb.StartExecutionRequest(
        workflow_id='workflow', graph=pb.WorkflowGraph(nodes=[
            pb.WorkflowNode(id='source', plugin_id='input_streamer'),
        ]),
    ), mock_context)
    await asyncio.wait_for(started.wait(), 2)
    task = service._execution_tasks[response.execution_id]
    cancelled = await asyncio.wait_for(service.CancelExecution(
        pb.CancelExecutionRequest(execution_id=response.execution_id), mock_context,
    ), 2)
    assert cancelled.success
    assert stopped.is_set()
    assert task.cancelled()
    assert response.execution_id not in service._execution_tasks
    assert response.execution_id not in service._active_routers
    row = await test_session.get(WorkflowExecutionModel, response.execution_id)
    assert row.state == 'CANCELLED'
    assert row.finished_at is not None


@pytest.mark.asyncio
async def test_repeated_cancel_preserves_async_worker_cleanup(test_session, mock_context):
    import asyncio
    from src.models import WorkflowExecutionModel
    started, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))
    service = OrchestratorServiceImpl()

    async def worker(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()

    service.container_manager.start_plugin_node = worker
    response = await service.StartExecution(pb.StartExecutionRequest(
        workflow_id='workflow', graph=pb.WorkflowGraph(nodes=[
            pb.WorkflowNode(id='source', plugin_id='input_streamer'),
        ]),
    ), mock_context)
    await asyncio.wait_for(started.wait(), 2)
    worker_task = service._execution_tasks[response.execution_id]
    request = pb.CancelExecutionRequest(execution_id=response.execution_id)
    first = asyncio.create_task(service.CancelExecution(request, type(mock_context)()))
    await asyncio.wait_for(cleaning.wait(), 2)
    # Cancelling the caller must not cancel the worker cleanup again.
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(service.CancelExecution(request, type(mock_context)()))
    await asyncio.sleep(0.02)
    assert not worker_task.done()
    release.set()
    assert (await asyncio.wait_for(second, 2)).success
    assert cleaned.is_set()
    assert worker_task.cancelled()
    row = await test_session.get(WorkflowExecutionModel, response.execution_id)
    assert row.state == 'CANCELLED'
