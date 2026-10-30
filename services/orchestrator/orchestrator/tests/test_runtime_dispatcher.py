import asyncio
from contextlib import asynccontextmanager

import pytest

from src.engine.runtime_dispatcher import RuntimeStreamDispatcher


async def empty():
    if False:
        yield None


def stream(dispatcher):
    return dispatcher.stream_node(execution_id='execution', node={'id':'node'}, inputs=empty(),
        ownership=('worker',1), initial_inputs={})


@pytest.mark.asyncio
async def test_reservation_precedes_provisioning_and_stop_cancels_it():
    entered, cleaned = asyncio.Event(), asyncio.Event()
    calls = []
    @asynccontextmanager
    async def assignments(**scope):
        calls.append(scope)
        try:
            entered.set()
            await asyncio.Event().wait()
            yield {}
        finally:
            cleaned.set()
    dispatcher = RuntimeStreamDispatcher(assignments)
    task = asyncio.create_task(anext(stream(dispatcher)))
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(RuntimeError, match='already active'):
        await anext(stream(dispatcher))
    await dispatcher.stop_node('execution','node')
    assert task.cancelled() and cleaned.is_set() and len(calls) == 1
    assert not dispatcher._tasks


@pytest.mark.asyncio
async def test_reservation_survives_assignment_teardown(monkeypatch):
    import src.engine.runtime_dispatcher as module
    from generated.protos.plugins import index_pb2 as pb
    cleaning, release = asyncio.Event(), asyncio.Event()
    @asynccontextmanager
    async def assignments(**scope):
        try:
            yield {'endpoint':'endpoint','token':'token','outputs':['out']}
        finally:
            cleaning.set()
            await release.wait()
    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def process(self, *args):
            yield pb.DataChunk(stream_name='out',sequence_number=0,payload=b'data',is_last=True)
    monkeypatch.setattr(module,'PluginRuntimeClient',Client)
    dispatcher = RuntimeStreamDispatcher(assignments)
    async def collect():
        return [item async for item in stream(dispatcher)]
    task = asyncio.create_task(collect())
    await asyncio.wait_for(cleaning.wait(), 1)
    with pytest.raises(RuntimeError, match='already active'):
        await anext(stream(dispatcher))
    release.set()
    frames = await task
    assert frames[0].sequence == 0 and frames[0].payload == b'data' and frames[0].is_last
    assert not dispatcher._tasks


@pytest.mark.asyncio
async def test_agent_lifecycle_wraps_stream_and_assignment(monkeypatch):
    import src.engine.runtime_dispatcher as module
    events = []
    @asynccontextmanager
    async def assignments(**scope):
        try:
            yield {'endpoint':'runtime','token':'runtime-token','outputs':[],
                'control':{'endpoint':'agent','token':'control-token','command_id':'attempt-1'}}
        finally:
            events.append('assignment-cleanup')
    class Control:
        def __init__(self, endpoint, execution, node, token, **kwargs):
            assert (endpoint,execution,node,token) == ('agent','execution','node','control-token')
        async def __aenter__(self): return self
        async def __aexit__(self,*args): events.append('control-close')
        @asynccontextmanager
        async def running(self, command):
            assert command == 'attempt-1'
            events.append('start')
            try: yield self
            finally: events.append('stop')
    class Runtime:
        def __init__(self,*args,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): events.append('runtime-close')
        async def process(self,*args):
            events.append('stream')
            raise RuntimeError('runtime failure')
            yield
    monkeypatch.setattr(module,'PluginControlClient',Control)
    monkeypatch.setattr(module,'PluginRuntimeClient',Runtime)
    dispatcher = RuntimeStreamDispatcher(assignments)
    with pytest.raises(RuntimeError,match='runtime failure'):
        await anext(stream(dispatcher))
    assert events == ['start','stream','runtime-close','stop','control-close','assignment-cleanup']
    assert not dispatcher._tasks
