import asyncio
import pytest
from templates import env


def helper():
    namespace = {}
    exec(compile(env.get_template('services/sqlalchemy/transactions.py.j2').render(), '<transactions>', 'exec'), namespace)
    return namespace['run_transaction']


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_commit_and_connection_close():
    started, release = asyncio.Event(), asyncio.Event()
    events = []
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): events.append('close')
        async def commit(self): events.append('commit')
        async def rollback(self): events.append('rollback')
    async def operation(session):
        started.set()
        await release.wait()
        events.append('write')
    task = asyncio.create_task(helper()(Session, operation))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ['write','commit','close']


@pytest.mark.asyncio
async def test_database_failure_rolls_back_before_propagating():
    events = []
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): events.append('close')
        async def commit(self): events.append('commit')
        async def rollback(self): events.append('rollback')
    async def operation(session):
        raise RuntimeError('database failure')
    with pytest.raises(RuntimeError, match='database failure'):
        await helper()(Session, operation)
    assert events == ['rollback','close']
