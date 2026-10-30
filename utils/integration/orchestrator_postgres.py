"""Real PostgreSQL lease checks in a disposable, locally bound Docker container."""
import asyncio
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
from src.engine.launch import prepare_launch, begin_launch


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
        async with factory() as session:
            attempt_id = await prepare_launch(session, execution_id='integration', node_id='node',
                owner=owner, fence=fence, role='plugin', image='registry/plugin@sha256:'+'a'*64,
                daemon_id='integration-daemon')
            await session.commit()
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
        print('PostgreSQL: 12 concurrent lease claimants, 12 launch claimants, fencing replacement and cancellation checks passed.')
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
