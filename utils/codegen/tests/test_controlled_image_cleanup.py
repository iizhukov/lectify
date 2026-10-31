"""The image probe must clean its daemon container after a CLI timeout."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('owned',[True,False])
def test_probe_timeout_removes_only_its_labelled_container(monkeypatch,owned):
    path = Path(__file__).resolve().parents[2] / 'integration/controlled_image.py'
    spec = importlib.util.spec_from_file_location('controlled_image_probe',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module,'sources',lambda *args:None)
    calls = []
    identity = None
    def run(command,**kwargs):
        nonlocal identity
        calls.append(command)
        if command[1] == 'build':
            identity = command[command.index('-t')+1].split(':')[1]
            Path(command[command.index('--iidfile')+1]).write_text('sha256:test')
        elif command[1] == 'run':
            raise subprocess.TimeoutExpired(command,30)
        elif command[1] == 'inspect':
            return subprocess.CompletedProcess(command,0,(identity if owned else 'foreign')+'\n','')
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(module.subprocess,'run',run)
    with pytest.raises(subprocess.TimeoutExpired):
        module.main()
    assert (['docker','rm','-f','lectify-controlled-check-'+identity] in calls) is owned
    assert ['docker','image','rm','lectify-controlled-check:'+identity] in calls
