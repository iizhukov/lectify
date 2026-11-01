import sys
import os
from pathlib import Path


codegen_dir = Path(__file__).resolve().parent.parent
repo_root = codegen_dir.parent.parent

if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

if str(codegen_dir / "src") not in sys.path:
    sys.path.insert(0, str(codegen_dir / "src"))

os.environ["CODEGEN_ROOT"] = str(repo_root)

