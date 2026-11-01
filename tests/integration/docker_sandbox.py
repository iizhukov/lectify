"""Exercise generated Docker transport against an already cached Python image."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'services/orchestrator/orchestrator'))
from generated.docker_sandbox import DockerSandbox


def inspect_image(context):
    raw = subprocess.check_output(['docker', '--context',context,'image', 'inspect', 'python:3.12-slim',
        '--format', '{{json .RepoDigests}}'], text=True)
    digests = json.loads(raw)
    if not digests:
        raise RuntimeError('A locally cached digest-pinned Python image is required')
    return digests[0]


async def main():
    context = subprocess.check_output(['docker','context','show'],text=True).strip()
    sandbox = DockerSandbox(context=context)
    assignment = dict(execution_id=uuid.uuid4().hex, node_id='integration', fence=1,
        attempt_id=uuid.uuid4().hex, image=inspect_image(context), environment={}, network='none')
    async with sandbox.launched(**assignment) as container_id:
        raw = subprocess.check_output(['docker','--context',context,'inspect','--format',
            '{{json .HostConfig}}',container_id], text=True)
        config = json.loads(raw)
        assert config['ReadonlyRootfs'] and config['NetworkMode'] == 'none'
        assert config['Memory'] == 512 * 1048576 and config['PidsLimit'] == 128
        assert 'ALL' in config['CapDrop']
        assert 'no-new-privileges:true' in config['SecurityOpt']
        assert await sandbox.state(container_id) in ('running','exited')
    scope = {key:assignment[key] for key in ('execution_id','node_id','fence','attempt_id')}
    assert await sandbox.reconcile(**scope) is False
    print('DockerSandbox: real create/start/security limits/removal and repeat reconciliation passed.')


if __name__ == '__main__':
    asyncio.run(main())
