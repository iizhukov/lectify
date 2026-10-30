"""Build only explicitly selected sources, run the real gRPC plugin smoke in Docker."""
import asyncio
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'services/orchestrator/orchestrator'))
from generated.docker_sandbox import DockerSandbox


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT).strip()


async def run(image):
    sandbox = DockerSandbox()
    async with sandbox.launched(execution_id=uuid.uuid4().hex, node_id='plugin-smoke', fence=1,
            attempt_id=uuid.uuid4().hex, image=image, environment={}, network='none') as container_id:
        for _ in range(300):
            state = await sandbox.state(container_id)
            if state == 'exited':
                code = docker('inspect','--format','{{.State.ExitCode}}',container_id)
                if code != '0':
                    raise RuntimeError('Container plugin gRPC smoke failed with exit code ' + code)
                break
            if state == 'dead':
                raise RuntimeError('Container plugin gRPC smoke died')
            await asyncio.sleep(0.1)
        else:
            raise TimeoutError('Container plugin gRPC smoke timed out')
    print('Docker: actual text_to_md runtime + scoped agent + runtime client passed with network none.')


def main():
    image = None
    with tempfile.TemporaryDirectory(prefix='lectify-plugin-smoke-') as directory:
        context = Path(directory)
        files = [
            'utils/integration/plugin_stream.py',
            'utils/integration/plugin_processes.py',
            'services/orchestrator/agent/src/policy.py',
            'services/orchestrator/agent/generated/plugin_agent/proxy.py',
            'services/orchestrator/orchestrator/generated/plugin_runtime_client.py',
        ]
        for relative in files:
            target = context / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        for relative in ('plugins/format/text_to_md/generated', 'plugins/format/text_to_md/src'):
            shutil.copytree(ROOT / relative, context / relative,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (context / 'Dockerfile').write_text('''FROM python:3.12-slim
WORKDIR /app
COPY plugins/format/text_to_md/generated/requirements.txt /tmp/requirements.txt
RUN pip install --disable-pip-version-check --timeout 15 --retries 1 --no-cache-dir -r /tmp/requirements.txt
COPY . /app
ENV PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
ENTRYPOINT ["python", "utils/integration/plugin_processes.py"]
''' + 'LABEL lectify.integration-build="' + uuid.uuid4().hex + '"\n')
        try:
            subprocess.run(['docker','build','--pull=false','--progress=plain','--iidfile',str(context / 'image.id'),
                str(context)], check=True, timeout=600)
            image = (context / 'image.id').read_text().strip()
            asyncio.run(run(image))
        finally:
            if image:
                docker('image','rm',image)


if __name__ == '__main__':
    main()
