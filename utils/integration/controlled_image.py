"""Build the generated controlled image using two allowlisted source contexts."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]


def sources(source, target):
    for name in ('generated', 'src'):
        shutil.copytree(source / name, target / name,
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))


def main():
    image = None
    identity = uuid.uuid4().hex
    tag = 'lectify-controlled-check:' + identity
    container = 'lectify-controlled-check-' + identity
    with tempfile.TemporaryDirectory(prefix='lectify-controlled-image-') as directory:
        root = Path(directory)
        runtime, agent = root / 'runtime', root / 'agent'
        sources(ROOT / 'plugins/format/text_to_md', runtime)
        sources(ROOT / 'services/orchestrator/agent', agent)
        try:
            subprocess.run(['docker','build','--pull=false','--progress=plain',
                '--build-context','lectify_agent=' + str(agent),
                '-f',str(runtime/'generated/Dockerfile.controlled'),'-t',tag,
                '--iidfile',str(root/'image.id'),str(runtime)],check=True,timeout=600)
            image = (root/'image.id').read_text().strip()
            # Explicit child env matches the controller: no agent PYTHONPATH.
            check = '''import os, subprocess, sys
assert os.getuid() == 1000
from generated.plugin_agent.server import create_server
from generated.plugin_agent.controller import PluginController
from src.service import create_agent
assert __import__('generated').__path__[0] == '/agent/generated'
subprocess.run([sys.executable, '-c',
    "from generated.server import create_server; from src.plugin import PluginHandler; "
    "assert __import__('generated').__path__[0] == '/runtime/generated'"],
    cwd='/runtime', env={'PYTHONDONTWRITEBYTECODE':'1'}, check=True, timeout=15)
'''
            subprocess.run(['docker','run','--rm','--name',container,
                '--label','lectify.integration-check=' + identity,'--network','none','--read-only',
                '--cap-drop','ALL','--security-opt','no-new-privileges',
                '--memory','512m','--pids-limit','128','--cpus','1',
                '-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','python',image,'-c',check],
                check=True,timeout=30)
            print('Generated controlled image: agent/runtime imports and nonroot isolation verified.')
        finally:
            # A run timeout cancels the CLI, not necessarily the daemon container.
            try:
                owned = subprocess.run(['docker','inspect','--format',
                    '{{index .Config.Labels "lectify.integration-check"}}',container],
                    capture_output=True,text=True,timeout=15)
                if owned.returncode == 0 and owned.stdout.strip() == identity:
                    subprocess.run(['docker','rm','-f',container],check=True,timeout=30,
                        stdout=subprocess.DEVNULL)
            finally:
                # Also attempted when inspect/removal fails; never prune other images.
                subprocess.run(['docker','image','rm',tag],check=False,timeout=30,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
