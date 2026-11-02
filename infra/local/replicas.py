"""Two orchestrator replicas on this computer; restores the usual single replica."""
import ipaddress
import json
import subprocess
import yaml
from backend import LOCAL,PROJECT,private_file
from recovery import EVIDENCE


def main():
    if not json.loads((LOCAL/'config/mode.json').read_text()).get('offline_test_provider'):
        raise RuntimeError('Replica probe requires up --test-provider')
    config=yaml.safe_load((LOCAL/'compose.yaml').read_text())
    config['services']['orchestrator'].pop('ports',None)
    path=LOCAL/'replicas.yaml'; private_file(path,yaml.safe_dump(config))
    base=['docker','compose','-p',PROJECT,'-f',str(LOCAL/'compose.yaml')]
    scaled=['docker','compose','-p',PROJECT,'-f',str(path)]
    try:
        subprocess.run(scaled+['up','-d','--no-deps','--no-build','--scale','orchestrator=2','orchestrator'],check=True)
        ids=subprocess.check_output(scaled+['ps','-q','orchestrator'],text=True).split()
        assert len(ids)==2
        workers=subprocess.check_output(base+['ps','-q','orchestrator_worker'],text=True).split()
        assert len(workers)==1
        endpoints=[]
        for id in ids:
            value=subprocess.check_output(['docker','inspect','--format','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',id],text=True).strip()
            ipaddress.IPv4Address(value); endpoints.append(value+':10040')
        subprocess.run(base+['exec','-T','api_execution','python','/app/infra/local/ready.py'],check=True)
        # Individual direct connections force each server to handle the same Start.
        with (LOCAL.parent.parent/'infra/local/replica_client.py').open() as source:
            result=subprocess.run(base+['exec','-T','-w','/app/infra/local','api_execution','python','-',*endpoints],
                stdin=source,text=True,capture_output=True,check=True)
        id=next(line.removeprefix('EXECUTION ') for line in result.stdout.splitlines() if line.startswith('EXECUTION '))
        output=subprocess.check_output(base+['exec','-T','--index','1','orchestrator','python','-c',EVIDENCE,id],text=True)
        evidence=json.loads(next(line.removeprefix('EVIDENCE ') for line in output.splitlines() if line.startswith('EVIDENCE ')))
        assert evidence['source_launches']==1 and evidence['source_ready'],evidence
        print('PASS: two local orchestrator replicas + one host agent → concurrent idempotent Start → shared pause/resume → source launched once → correct S3 result')
    finally:
        subprocess.run(base+['up','-d','--no-deps','--no-build','--scale','orchestrator=1','orchestrator'],check=True)
        path.unlink(missing_ok=True)


if __name__=='__main__': main()
