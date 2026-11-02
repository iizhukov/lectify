"""Local deployment startup: apply codegen migrations, then run generated service."""
import asyncio
import os
from pathlib import Path
import sys

async def prepare():
    if os.environ.get('LOCAL_TEST_PROVIDER') == '1' and os.environ['LOCAL_SERVICE']=='plugins_provider':
        import subprocess
        import socket
        fixture=subprocess.Popen([sys.executable,'/app/infra/local/test_provider.py'])
        async with asyncio.timeout(10):
            while True:
                if fixture.poll() is not None: raise RuntimeError('Offline test provider failed to start')
                try:
                    with socket.create_connection(('127.0.0.1',18080),timeout=.2): break
                except OSError: await asyncio.sleep(.1)
    if Path('migrations/versions').exists():
        sys.path.insert(0, '/app/utils/codegen/src')
        from migrations.migration_executor import MigrationExecutor
        result = await MigrationExecutor(os.environ['LOCAL_DB_URL'],Path('migrations').resolve()).migrate()
        if result.errors:
            raise RuntimeError('Database migration failed')
    if os.environ['LOCAL_SERVICE'] == 'api_auth':
        sys.path.insert(0,str(Path.cwd()))
        from generated.db.connection import get_session_factory
        from src.models import User
        from src.passwords import hash_password
        from sqlalchemy import select
        import uuid
        async with get_session_factory()() as session:
            user = await session.scalar(select(User).where(User.username == 'admin'))
            if user is None:
                session.add(User(id=str(uuid.uuid4()),username='admin',email='admin@local.invalid',full_name='Local admin',
                    password_hash=hash_password(os.environ['LOCAL_ADMIN_PASSWORD']),is_admin=True,security_version=0))
                await session.commit()
    if os.environ['LOCAL_SERVICE'] == 'api_file':
        import boto3
        from botocore.exceptions import ClientError
        client = boto3.client('s3',endpoint_url='http://minio:9000',
            aws_access_key_id=os.environ['API_FILE_MINIO_ACCESS_KEY'],
            aws_secret_access_key=os.environ['API_FILE_MINIO_SECRET_KEY'])
        async with asyncio.timeout(30):
            while True:
                try:
                    await asyncio.to_thread(client.create_bucket,Bucket='user-files')
                    break
                except ClientError as error:
                    if error.response['Error']['Code'] in ('BucketAlreadyOwnedByYou','BucketAlreadyExists'):
                        break
                    raise
                except Exception:
                    await asyncio.sleep(.5)

if __name__ == '__main__':
    if 'LECTIFY_AGENT_ASSIGNMENT_JSON' in os.environ:
        os.chdir('/app/services/orchestrator/agent')
        os.execv(sys.executable,[sys.executable,'-c',
            'import asyncio; from generated.plugin_agent.server import run_server; asyncio.run(run_server())'])
    os.chdir('/app/' + sys.argv[1])
    asyncio.run(prepare())
    os.execv(sys.executable,[sys.executable,'-m','generated.main'])
