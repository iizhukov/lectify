"""Fresh codegen + SQLite persistence + real gRPC, isolated from other services."""
from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[4]
SERVICE = Path(__file__).resolve().parents[1]


def test_prompt_contract(tmp_path):
    environment = dict(os.environ, CODEGEN_ROOT=str(ROOT), PROMPT_SOURCE=str(SERVICE))
    result = subprocess.run([sys.executable, str(SERVICE / 'tests/scenario.py'), str(tmp_path)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
