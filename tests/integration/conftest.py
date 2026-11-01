"""Codegen imports used by integration fixtures."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "utils/codegen/src"))
os.environ.setdefault("CODEGEN_ROOT", str(ROOT))
