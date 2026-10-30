import asyncio

import pytest
from config.models import ServiceManifest
from templates import env


@pytest.mark.asyncio
async def test_concurrent_close_and_repeated_cancel_settle_each_resource_once():
    manifest = ServiceManifest.model_validate({'service':{'name':'cleanup_test'}})
    source = env.get_template('services/grpc/client/grpc_clients.py.j2').render(
        manifest=manifest,service=manifest.service,client_services=[])
    namespace = {}
    exec(compile(source,'<grpc clients>','exec'),namespace)
    clients = namespace['GrpcClients']()
    entered, release = asyncio.Event(), asyncio.Event()
    started, completed = [], []
    class Resource:
        def __init__(self,name): self.name=name
        async def close(self):
            started.append(self.name)
            entered.set()
            await release.wait()
            completed.append(self.name)
    clients._channels['backend'] = Resource('channel')
    clients._interceptor_resources.append(Resource('interceptor'))
    first = asyncio.create_task(clients.close_all())
    await entered.wait()
    first.cancel()
    await asyncio.sleep(0)
    second = asyncio.create_task(clients.close_all())
    first.cancel()
    await asyncio.sleep(0)
    assert not first.done() and not second.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    await clients.close_all()
    assert sorted(started) == sorted(completed) == ['channel','interceptor']
    with pytest.raises(RuntimeError,match='closed'):
        clients.channel('backend')
