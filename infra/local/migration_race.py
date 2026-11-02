"""Exercise universal migration locking in two processes against a disposable PostgreSQL DB."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0,'/app/utils/codegen/src')
from migrations.constants import MIGRATIONS_TABLE

CHILD='''
import asyncio,os,sys
from pathlib import Path
sys.path.insert(0,'/app/utils/codegen/src')
from migrations.migration_executor import MigrationExecutor
async def main():
    result=await MigrationExecutor(os.environ['MIGRATION_RACE_URL'],Path(sys.argv[1])).migrate()
    assert not result.errors, 'Concurrent migration failed'
asyncio.run(main())
'''


async def main():
    url=make_url(os.environ['LOCAL_DB_URL'])
    name='codegen_race_'+uuid.uuid4().hex
    engine=create_async_engine(url,isolation_level='AUTOCOMMIT')
    created=False
    try:
        async with engine.connect() as connection:
            await connection.execute(text('CREATE DATABASE '+name)); created=True
        isolated=url.set(database=name)
        with tempfile.TemporaryDirectory(prefix='migration-race-') as directory:
            root=Path(directory); (root/'versions').mkdir()
            (root/'versions/0001_race.py').write_text("""from alembic import op
import sqlalchemy as sa
revision='0001_race'
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    op.execute('SELECT pg_sleep(0.5)')
    op.create_table('race_result',sa.Column('id',sa.Integer(),primary_key=True))
    op.execute('INSERT INTO race_result VALUES (1)')
def downgrade():op.drop_table('race_result')
""")
            env=dict(os.environ,MIGRATION_RACE_URL=isolated.render_as_string(hide_password=False))
            children=[subprocess.Popen([sys.executable,'-c',CHILD,directory],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
            try:
                for child in children:
                    await asyncio.to_thread(child.communicate,timeout=30)
                    assert child.returncode==0,'A concurrent migration process failed'
            finally:
                for child in children:
                    if child.poll() is None: child.kill(); child.wait()
            check=create_async_engine(isolated)
            try:
                async with check.connect() as connection:
                    assert await connection.scalar(text('SELECT count(*) FROM race_result'))==1
                    assert await connection.scalar(text('SELECT count(*) FROM '+MIGRATIONS_TABLE))==1
            finally: await check.dispose()
        print('PASS: two migration processes → one applied schema/data change; connection URL never written to ini')
    finally:
        if created:
            async with engine.connect() as connection:
                await connection.execute(text('DROP DATABASE '+name))
        await engine.dispose()


if __name__=='__main__': asyncio.run(main())
