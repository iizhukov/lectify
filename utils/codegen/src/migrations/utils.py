import re
import sys

from pathlib import Path
from typing import Optional

from .constants import TYPE_NORMALIZE, SA_TYPE_MAPPING, REVISION_PATTERN, REVISION_FORMAT
from .patterns import MigrationPatterns


class TypeNormalizer:
    @staticmethod
    def normalize_type(type_str: str) -> str:
        type_str = str(type_str).strip().upper()
        match = MigrationPatterns.TYPE_WITH_PARAMS.match(type_str)
        
        if match:
            base = match.group(1)
            params = match.group(2)
            normalized_base = TYPE_NORMALIZE.get(base, base)
            return f"{normalized_base}({params})"
        
        return TYPE_NORMALIZE.get(type_str, type_str)
    
    @staticmethod
    def get_sa_type(type_str: str) -> str:
        clean = type_str.upper()
        match = MigrationPatterns.TYPE_WITH_PARAMS.match(clean)
        
        if match:
            base = match.group(1)
            params = match.group(2)
            sa_base = SA_TYPE_MAPPING.get(base, base.capitalize())
            return f"sa.{sa_base}({params})"
        
        sa_base = SA_TYPE_MAPPING.get(clean, clean.capitalize())
        return f"sa.{sa_base}"


class MigrationFileUtils:    
    @staticmethod
    def get_next_revision_id(migrations_dir: Path) -> str:
        versions_dir = migrations_dir / "versions"
        if not versions_dir.exists():
            return "0001"
        
        existing = []
        for path in versions_dir.glob("*.py"):
            if path.stem == "__init__":
                continue
            match = re.match(REVISION_PATTERN, path.stem)
            if match:
                existing.append(int(match.group(1)))
        
        return REVISION_FORMAT.format((max(existing) + 1) if existing else 1)
    
    @staticmethod
    def find_head_revision(migrations_dir: Path) -> Optional[str]:
        versions_dir = migrations_dir / "versions"
        if not versions_dir.exists():
            return None
        
        revisions = sorted([
            p for p in versions_dir.glob("*.py")
            if p.stem != "__init__" and re.match(REVISION_PATTERN, p.stem)
        ])
        
        if not revisions:
            return None
        
        content = revisions[-1].read_text()
        match = MigrationPatterns.REVISION_ID.search(content)
        return match.group(1) if match else None
    
    @staticmethod
    def parse_migration_name(filename: str) -> tuple:
        match = re.match(r"^(\d{4})_(.+)$", filename)
        if match:
            return int(match.group(1)), match.group(2)
        return 0, filename


class SettingsLoader:    
    @staticmethod
    def load_settings(service_root: Path):
        if str(service_root) not in sys.path:
            sys.path.insert(0, str(service_root))
        
        try:
            from generated.settings import get_settings
            return get_settings()
        except ImportError:
            raise ImportError("Cannot import get_settings from generated.settings")
