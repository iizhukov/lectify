"""Real PostgreSQL lease checks in a disposable, locally bound Docker container."""
import asyncio
import json
from pathlib import Path
import secrets
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'services/orchestrator/orchestrator'))
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from generated.db.base import BaseModel
from src.models import WorkflowExecutionModel as Execution, WorkflowDispatchModel as Dispatch, WorkflowNodeExecutionModel as Node
from src.engine.dispatch import claim, renew, guard_execution_write
from src.engine.launch import prepare_worker_launch, begin_launch
from generated.docker_workers import DockerWorkers


async def verify_start_idempotency(factory):
    from types import SimpleNamespace
    from generated.db.connection import set_session_factory
    from generated.protos.server import index_pb2 as pb
    from src.service import OrchestratorServiceImpl
    class Context:
        lectify_principal = SimpleNamespace(user_id='integration-user',is_admin=False)
        async def abort(self, code, details):
            raise RuntimeError('Unexpected RPC rejection: '+code.name)
    class Runner:
        def __init__(self):
            self.started, self.calls = asyncio.Event(), 0
        async def start_plugin_node(self, **scope):
            self.calls += 1
            self.started.set()
            await asyncio.Event().wait()
    runner = Runner()
    services = [OrchestratorServiceImpl(container_manager=runner) for _ in range(2)]
    request = pb.StartExecutionRequest(execution_id='integration-start',workflow_id='workflow',
        graph=pb.WorkflowGraph(nodes=[pb.WorkflowNode(id='node',plugin_id='plugin')]))
    set_session_factory(factory)
    try:
        responses = await asyncio.wait_for(asyncio.gather(*(
            service.StartExecution(request,Context()) for service in services)),15)
        await asyncio.wait_for(runner.started.wait(),5)
        assert responses[0].execution_id == responses[1].execution_id
        assert responses[0].started_at == responses[1].started_at
        assert runner.calls == 1
        class Admin(Context):
            lectify_principal = SimpleNamespace(user_id='integration-admin',is_admin=True)
        plugin = pb.RegisterPluginManifestRequest(plugin_id='integration_plugin',version='0.1.0',
            manifest_yaml='plugin: {name: integration_plugin, version: "0.1.0"}')
        registrations = await asyncio.wait_for(asyncio.gather(*(
            services[index % 2].RegisterPluginManifest(plugin,Admin()) for index in range(12))),15)
        assert all(result.success for result in registrations)
        async with factory() as session:
            assert await session.scalar(text("SELECT count(*) FROM plugin_registry WHERE id='integration_plugin'")) == 1
        class InvalidManifest(Exception): pass
        class RejectInvalid(Admin):
            async def abort(self,code,details):
                assert code.name == 'INVALID_ARGUMENT',code
                raise InvalidManifest()
        for metadata in ({'category':'x'*65},{'description':'bad\x00text'},{'description':'bad\ud800text'}):
            invalid = pb.RegisterPluginManifestRequest(plugin_id='invalid_plugin',version='0.1.0',
                manifest_yaml=json.dumps({'plugin':{'name':'invalid_plugin','version':'0.1.0',**metadata}}))
            try: await services[0].RegisterPluginManifest(invalid,RejectInvalid())
            except InvalidManifest: pass
            else: raise AssertionError('Invalid registry metadata reached PostgreSQL')
    finally:
        for service in services:
            await service.CancelExecution(pb.CancelExecutionRequest(execution_id=request.execution_id),Context())
            await asyncio.gather(*list(service._execution_tasks.values()),return_exceptions=True)
        set_session_factory(None)


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT).strip()


async def verify(port, password):
    engine = create_async_engine(f'postgresql+asyncpg://postgres:{password}@127.0.0.1:{port}/postgres')
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        # The image first starts a temporary Unix-socket server for initialization.
        # Readiness must use the same published TCP endpoint as the actual checks.
        for attempt in range(100):
            try:
                async with engine.connect() as connection:
                    await connection.execute(text('SELECT 1'))
                break
            except (ConnectionError, OSError, DBAPIError):
                if attempt == 99:
                    raise
                await asyncio.sleep(0.2)
        async with engine.begin() as connection:
            await connection.run_sync(BaseModel.metadata.create_all)
        async with factory() as session:
            session.add(Execution(id='integration', workflow_id='workflow', state='RUNNING'))
            await session.flush()
            session.add(Dispatch(execution_id='integration'))
            session.add(Node(execution_id='integration', node_id='node', plugin_id='plugin'))
            await session.commit()
        ready = asyncio.Event()
        async def compete(owner):
            async with factory() as session:
                await ready.wait()
                fence = await claim(session, 'integration', owner)
                await session.commit()
                return owner, fence
        tasks = [asyncio.create_task(compete(f'worker-{i}')) for i in range(12)]
        ready.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 15)
        winners = [(owner, fence) for owner, fence in results if fence is not None]
        assert len(winners) == 1, results
        owner, fence = winners[0]
        assert fence == 1
        workers = {'integration-daemon-a':object(),'integration-daemon-b':object()}
        async def place(index):
            inventory = workers if index % 2 else dict(reversed(tuple(workers.items())))
            async with factory() as session:
                result = await prepare_worker_launch(session,DockerWorkers(inventory),
                    execution_id='integration',node_id='node',owner=owner,fence=fence,
                    role='plugin',image='registry/plugin@sha256:'+'a'*64)
                await session.commit()
                return result[:2]
        placements = await asyncio.wait_for(asyncio.gather(*(place(i) for i in range(12))),15)
        assert len(set(placements)) == 1, placements
        attempt_id, assigned_daemon = placements[0]
        assert assigned_daemon in workers
        async def compete_launch():
            async with factory() as session:
                won = await begin_launch(session, attempt_id=attempt_id, execution_id='integration',
                    owner=owner, fence=fence)
                await session.commit()
                return won
        launch_results = await asyncio.wait_for(asyncio.gather(*(compete_launch() for _ in range(12))), 15)
        assert sum(launch_results) == 1, launch_results
        async with factory() as session:
            assert await renew(session, 'integration', owner, fence)
            await session.commit()
            await session.execute(update(Dispatch).where(Dispatch.execution_id == 'integration').values(lease_expires_at=0))
            await session.commit()
            replacement = await claim(session, 'integration', 'replacement')
            await session.commit()
            assert replacement == 2
            assert not await guard_execution_write(session, 'integration', (owner, fence))
            await session.rollback()
            assert await guard_execution_write(session, 'integration', ('replacement', replacement))
            await session.execute(update(Execution).where(Execution.id == 'integration').values(state='CANCELLED'))
            await session.commit()
            assert not await renew(session, 'integration', 'replacement', replacement)
            await session.commit()
            assert await claim(session, 'integration', 'late', now=9999999999) is None
            await session.commit()
        await verify_start_idempotency(factory)
        print('PostgreSQL: concurrent lease/launch claims, fencing, cancellation and two-replica StartExecution idempotency passed.')
    finally:
        await engine.dispose()


async def main():
    container = None
    password = secrets.token_hex(24)
    try:
        container = docker('run', '--rm', '-d', '--name', 'lectify-lease-check-' + uuid.uuid4().hex[:10],
            '--memory', '256m', '--cpus', '1', '--tmpfs', '/var/lib/postgresql/data',
            '-e', 'POSTGRES_PASSWORD=' + password, '-p', '127.0.0.1::5432', 'postgres:16-alpine')
        for _ in range(100):
            result = subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'postgres'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError('Temporary PostgreSQL did not become ready')
        port = int(docker('port', container, '5432/tcp').rsplit(':', 1)[1])
        await verify(port, password)
    finally:
        if container:
            docker('rm', '-f', container)
            print('Temporary PostgreSQL container removed.')


if __name__ == '__main__':
    asyncio.run(main())
