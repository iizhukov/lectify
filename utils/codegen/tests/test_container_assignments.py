from contextlib import asynccontextmanager
import pytest
from templates import env


@pytest.mark.asyncio
async def test_launch_failure_revokes_grant_and_unknown_plugin_never_provisions():
    namespace = {}
    exec(env.get_template('services/container_assignments.py.j2').render(),namespace)
    events = []
    async def prepare(**scope):
        events.append('prepare')
        assert scope['image'] == 'sha256:'+'a'*64
        return {'attempt_id':'b'*32,'daemon_id':'daemon'}
    @asynccontextmanager
    async def grants(**scope):
        events.append('grant')
        try:
            yield {'environment':{},'runtime':{'control':{}}}
        finally: events.append('revoke')
    @asynccontextmanager
    async def launch(**scope):
        events.append('launch')
        raise RuntimeError('daemon unavailable')
        yield
    resolver = namespace['ContainerRuntimeAssignments'](
        images={('plugin','0.1.0'):'sha256:'+'a'*64},prepare=prepare,launch=launch,grants=grants)
    scope = dict(execution_id='execution',ownership=('owner',1),initial_inputs={})
    with pytest.raises(RuntimeError,match='daemon unavailable'):
        async with resolver(**scope,node={'id':'node','plugin_id':'plugin'}):
            pytest.fail('Unavailable container yielded an assignment')
    assert events == ['prepare','grant','launch','revoke']
    with pytest.raises(RuntimeError,match='no trusted deployment image'):
        async with resolver(**scope,node={'id':'node','plugin_id':'unknown'}):
            pytest.fail('Unknown image provisioned')
    assert events == ['prepare','grant','launch','revoke']
