"""Single-host recovery probe. Only restarts the local Compose orchestrator."""
import json
from pathlib import Path
import re
import subprocess
import sys
from backend import LOCAL,PROJECT

COMPOSE=['docker','compose','-p',PROJECT,'-f',str(LOCAL/'compose.yaml')]
EVIDENCE=r'''
import asyncio,json,os,sys
os.chdir('/app/services/orchestrator/orchestrator'); sys.path.insert(0,os.getcwd())
from sqlalchemy import select,func
from generated.db.connection import get_session_factory,get_engine
from src.models import WorkflowExecutionModel as E,WorkflowNodeExecutionModel as N,ContainerAttemptModel as A
async def main():
    id=sys.argv[1]
    async with get_session_factory()() as session:
        async def launches(node):
            return await session.scalar(select(func.count()).select_from(A).where(A.execution_id==id,A.node_id==node,A.role=='plugin'))
        print('EVIDENCE '+json.dumps(dict(source_launches=await launches('source'),llm_launches=await launches('llm'),
            source_ready=await session.scalar(select(N.checkpoint_ready).where(N.execution_id==id,N.node_id=='source')),
            automatic_retries=await session.scalar(select(E.automatic_retries).where(E.id==id)),
            unclean_attempts=await session.scalar(select(func.count()).select_from(A).where(A.execution_id==id,A.state!='CLEANED')))))
    await get_engine().dispose()
asyncio.run(main())
'''


def checked(*args,**kwargs):
    return subprocess.run(COMPOSE+list(args),check=True,**kwargs)


def main():
    mode=json.loads((LOCAL/'config/mode.json').read_text())
    if not mode.get('offline_test_provider'): raise RuntimeError('Use up --test-provider before recovery')
    child=subprocess.Popen(COMPOSE+['exec','-T','api_execution','python','/app/infra/local/recovery_client.py'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    killed=False
    try:
        for line in child.stdout:
            if not line.startswith('HOST '):
                print(line,end='',flush=True); continue
            _,action,value=line.strip().split(' ',2)
            if action=='OBSERVE':
                if not re.fullmatch('[a-f0-9]{64}',value): raise ValueError('Invalid fixture observation identity')
                code='import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:18080/observations/'+value+'",timeout=3).read().decode())'
                reply=json.loads(checked('exec','-T','plugins_provider','python','-c',code,capture_output=True,text=True).stdout)
            elif action=='EVIDENCE':
                if not re.fullmatch('[a-f0-9-]{36}',value): raise ValueError('Invalid execution identity')
                output=checked('exec','-T','orchestrator','python','-c',EVIDENCE,value,capture_output=True,text=True).stdout
                reply=json.loads(next(row.removeprefix('EVIDENCE ') for row in output.splitlines() if row.startswith('EVIDENCE ')))
            elif action=='RESTART':
                print('Restarting only the local orchestrator with SIGKILL',flush=True)
                killed=True
                checked('kill','-s','SIGKILL','orchestrator',stdout=subprocess.DEVNULL)
                checked('up','-d','--no-deps','--no-build','orchestrator',stdout=subprocess.DEVNULL)
                killed=False; reply={'restarted':True}
            else: raise ValueError('Unknown recovery host action')
            child.stdin.write(json.dumps(reply)+'\n'); child.stdin.flush()
        if child.wait()!=0: raise RuntimeError('Local recovery probe failed')
    finally:
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        if killed: checked('up','-d','--no-deps','--no-build','orchestrator')


if __name__=='__main__': main()
