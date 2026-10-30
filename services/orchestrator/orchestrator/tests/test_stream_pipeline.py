import asyncio

import pytest

from src.engine.stream_pipeline import run_streaming_graph
from src.engine.stream_router import StreamChunkData as Frame


@pytest.mark.asyncio
async def test_concurrent_fanout_larger_than_queue_capacity_preserves_order_and_ports():
    nodes = [{'id':name} for name in ('source','left','right')]
    edges = [dict(from_node_id='source',from_output='out',to_node_id=name,to_input='input')
        for name in ('left','right')]
    received = {'left':[], 'right':[]}
    async def runner(node, inputs):
        if node['id'] == 'source':
            for sequence in range(250):
                yield Frame('out', str(sequence).encode(), sequence=sequence)
            yield Frame('out', b'', is_last=True, sequence=250)
        else:
            async for frame in inputs:
                assert frame.stream_name == 'input'
                if not frame.is_last:
                    received[node['id']].append(frame.payload)
                    await asyncio.sleep(0)
    await asyncio.wait_for(run_streaming_graph('execution', nodes, edges, runner), 5)
    assert received['left'] == received['right'] == [str(i).encode() for i in range(250)]


@pytest.mark.asyncio
async def test_consumer_failure_cancels_backpressured_producer():
    stopped = asyncio.Event()
    async def runner(node, inputs):
        if node['id'] == 'source':
            try:
                for sequence in range(10000):
                    yield Frame('out', b'data', sequence=sequence)
            finally:
                stopped.set()
        else:
            async for frame in inputs:
                raise RuntimeError('consumer failed')
    with pytest.raises(RuntimeError, match='consumer failed'):
        await asyncio.wait_for(run_streaming_graph('execution', [{'id':'source'},{'id':'sink'}],
            [dict(from_node_id='source',from_output='out',to_node_id='sink',to_input='in')], runner), 5)
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_missing_output_eof_fails_instead_of_hanging_consumer():
    async def runner(node, inputs):
        if node['id'] == 'source':
            yield Frame('out', b'incomplete')
        else:
            async for frame in inputs:
                pass
    with pytest.raises(ValueError, match='truncated'):
        await asyncio.wait_for(run_streaming_graph('execution', [{'id':'source'},{'id':'sink'}],
            [dict(from_node_id='source',from_output='out',to_node_id='sink',to_input='in')], runner), 5)


@pytest.mark.asyncio
async def test_repeated_graph_cancel_does_not_interrupt_adapter_cleanup():
    started, cleaning, release, cleaned = [asyncio.Event() for _ in range(4)]
    async def runner(node, inputs):
        try:
            started.set()
            await asyncio.Event().wait()
            if False:
                yield Frame('out', b'')
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()
    task = asyncio.create_task(run_streaming_graph('execution', [{'id':'source'}], [], runner))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    await asyncio.wait_for(cleaning.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
