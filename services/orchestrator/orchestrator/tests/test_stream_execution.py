import pytest
from sqlalchemy import select

from generated.stream_router import StreamChunkData as Frame
from src.engine.dag import WorkflowDAG
from src.models import WorkflowExecutionModel, WorkflowNodeExecutionModel
from src.service import OrchestratorServiceImpl


@pytest.mark.asyncio
@pytest.mark.parametrize('truncated', [False, True])
async def test_service_streaming_pipeline_persists_only_validated_completion(test_session, truncated):
    nodes = [{'id':'source','plugin_id':'source'}, {'id':'sink','plugin_id':'sink'}]
    edges = [dict(from_node_id='source',from_output='output',to_node_id='sink',to_input='input')]
    execution = WorkflowExecutionModel(id='stream-execution', workflow_id='workflow', state='RUNNING')
    test_session.add(execution)
    await test_session.flush()
    test_session.add_all([WorkflowNodeExecutionModel(execution_id=execution.id,node_id=node['id'],plugin_id=node['plugin_id'])
        for node in nodes])
    await test_session.commit()
    received = []
    class Dispatcher:
        supports_streaming = True
        async def stream_node(self, *, node, inputs, **scope):
            if node['id'] == 'source':
                yield Frame('output', b'payload')
                if not truncated:
                    yield Frame('output', b'', sequence=1, is_last=True)
            else:
                async for frame in inputs:
                    if not frame.is_last:
                        received.append(frame.payload)
    service = OrchestratorServiceImpl(container_manager=Dispatcher())
    await service._run_execution_pipeline(execution.id, nodes, WorkflowDAG(nodes,edges), {})
    await test_session.refresh(execution)
    assert execution.state == ('FAILED' if truncated else 'COMPLETED')
    rows = list(await test_session.scalars(select(WorkflowNodeExecutionModel).where(
        WorkflowNodeExecutionModel.execution_id == execution.id)))
    states = {row.state for row in rows}
    if truncated:
        assert 'FAILED' in states and states <= {'FAILED','PENDING'}
    else:
        assert states == {'COMPLETED'}
    if not truncated:
        assert received == [b'payload']
