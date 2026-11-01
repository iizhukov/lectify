from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
SERVICE = Path(__file__).resolve().parents[1]


def test_provider_contract(tmp_path):
    result = subprocess.run([sys.executable, str(SERVICE / 'tests/scenario.py'), str(tmp_path)],
        cwd=tmp_path, env=dict(os.environ, CODEGEN_ROOT=str(ROOT), PROVIDER_SOURCE=str(SERVICE)),
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
