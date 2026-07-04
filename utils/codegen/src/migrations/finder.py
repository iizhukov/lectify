import importlib
import sys

from pathlib import Path
from typing import Any, Optional, Type


class ModelFinder:
    def __init__(self, service_root: Path):
        self.service_root = service_root.resolve()
        self.src_dir = self.service_root / "src"
        
        if str(self.service_root) not in sys.path:
            sys.path.insert(0, str(self.service_root))
    
    def find_base_class(self) -> Optional[Type]:
        try:
            from generated.db.base import BaseModel
            print("[finder] Found BaseModel from generated.db.base")
            return BaseModel
        except ImportError:
            print("[finder] Not found BaseModel from generated.db.base")
            return None
    
    def get_metadata(self, base_class: Type) -> Any:
        self._import_all_modules()
        return base_class.metadata
    
    def _import_all_modules(self):
        if not self.src_dir.exists():
            return
        
        for py_file in self.src_dir.rglob("*.py"):
            if py_file.stem == "__init__":
                continue

            module_path = py_file.relative_to(self.service_root)
            module_name = str(module_path.with_suffix("")).replace("/", ".").replace("\\", ".")

            try:
                importlib.import_module(module_name)
            except Exception as e:
                print(f"[finder] Cannot import {module_name}: {e}")
