import asyncio

import pytest

from templates import env


def sandbox_class():
    namespace = {}
    exec(compile(env.get_template('services/docker_sandbox.py.j2').render(), '<sandbox>', 'exec'), namespace)
    return namespace['DockerSandbox']


SPEC = dict(execution_id='execution', node_id='node', fence=1,
    attempt_id='c'*32,
    image='registry/plugin@sha256:'+'a'*64, environment={'EXECUTION_ID':'execution'})


@pytest.mark.asyncio
async def test_sandbox_limits_and_cleanup_on_worker_cancellation():
    commands = []
    async def runner(*args):
        commands.append(args)
        return 'b'*64
    sandbox = sandbox_class()(runner=runner)
    entered = asyncio.Event()
    async def worker():
        async with sandbox.launched(**SPEC):
            entered.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(worker())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    create = commands[0]
    assert '--read-only' in create and '--cap-drop=ALL' in create
    assert '--network' in create and '--user=1000:1000' in create
    assert commands[1] == ('start', 'b'*64)
    assert commands[2] == ('rm', '--force', 'b'*64)


@pytest.mark.asyncio
@pytest.mark.parametrize('override', [
    {'image':'registry/plugin:latest'}, {'image':'--privileged'}, {'network':'host'},
    {'environment':{'LD_PRELOAD':'\x00'}}, {'fence':True},
])
async def test_sandbox_rejects_untrusted_launch_spec_before_docker(override):
    calls = []
    async def runner(*args):
        calls.append(args)
    with pytest.raises(ValueError):
        await sandbox_class()(runner=runner).create(**{**SPEC, **override})
    assert not calls


@pytest.mark.asyncio
async def test_cancellation_during_create_and_repeated_cleanup_cancel():
    creating, finish_create, removing, finish_remove = [asyncio.Event() for _ in range(4)]
    commands = []
    async def runner(*args):
        commands.append(args)
        if args[0] == 'create':
            creating.set()
            await finish_create.wait()
        if args[0] == 'rm':
            removing.set()
            await finish_remove.wait()
        return 'b'*64
    async def worker():
        async with sandbox_class()(runner=runner).launched(**SPEC):
            pytest.fail('Cancelled assignment must never start')
    task = asyncio.create_task(worker())
    await asyncio.wait_for(creating.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    finish_create.set()
    await asyncio.wait_for(removing.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish_remove.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [args[0] for args in commands] == ['create', 'rm']


@pytest.mark.asyncio
@pytest.mark.parametrize('matching', [True, False])
async def test_lost_create_response_only_cleans_verified_attempt(matching):
    commands = []
    async def runner(*args):
        commands.append(args)
        if args[0] == 'create':
            raise TimeoutError('lost response')
        if args[0] == 'container':
            return 'b'*64
        if args[0] == 'inspect':
            return 'b'*64 + ' true ' + ('c' if matching else 'd')*32
        return ''
    expected = TimeoutError if matching else RuntimeError
    with pytest.raises(expected):
        await sandbox_class()(runner=runner).create(**SPEC)
    assert [args[0] for args in commands] == (['create','container','inspect','rm'] if matching else ['create','container','inspect'])


@pytest.mark.asyncio
async def test_reconciliation_distinguishes_absence_from_daemon_failure():
    commands = []
    async def absent(*args):
        commands.append(args)
        return ''
    scope = {key:SPEC[key] for key in ('execution_id','node_id','fence','attempt_id')}
    assert await sandbox_class()(runner=absent).reconcile(**scope) is False
    assert len(commands) == 1 and commands[0][0] == 'container'
    async def unavailable(*args):
        raise TimeoutError('daemon unavailable')
    with pytest.raises(TimeoutError):
        await sandbox_class()(runner=unavailable).reconcile(**scope)


@pytest.mark.asyncio
async def test_locally_built_immutable_image_id_is_accepted():
    calls = []
    async def runner(*args):
        calls.append(args)
        return 'b'*64
    await sandbox_class()(runner=runner).create(**{**SPEC, 'image':'sha256:'+'d'*64})
    assert calls[0][-1] == 'sha256:'+'d'*64
    assert '--pull=never' in calls[0]
