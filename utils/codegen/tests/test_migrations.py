import sys
from pathlib import Path

from migrations.schema_builder import SchemaBuilder


def _cleanup_modules():
    for mod_name in list(sys.modules.keys()):
        if mod_name in ("generated", "src") or mod_name.startswith(("generated.", "src.")):
            del sys.modules[mod_name]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_service(service_root: Path) -> None:
    """Scaffold the minimal generated/ + src/ layout required by the schema builder."""
    _cleanup_modules()
    _write(
        service_root / "generated" / "db" / "__init__.py",
        "",
    )
    _write(
        service_root / "generated" / "db" / "base.py",
        """
from sqlalchemy.orm import DeclarativeBase


class BaseModel(DeclarativeBase):
    pass
""".strip()
        + "\n",
    )
    _write(
        service_root / "generated" / "settings" / "__init__.py",
        """
class _Database:
    url = "sqlite:///:memory:"

class _Settings:
    database = _Database()

_settings = _Settings()

def get_settings():
    return _settings
""".strip()
        + "\n",
    )
    _write(service_root / "generated" / "settings" / "base.py", "")
    _write(service_root / "src" / "__init__.py", "")
    _write(
        service_root / "src" / "models.py",
        """
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from generated.db.base import BaseModel


class User(BaseModel):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
""".strip()
        + "\n",
    )


def test_finder_discovers_models_from_service_src(tmp_path: Path) -> None:
    service_root = tmp_path
    _make_service(service_root)

    builder = SchemaBuilder(service_root)
    schema = builder.build_from_models()

    assert "users" in schema
    assert schema["users"].columns


def test_make_creates_migration_from_service_models(tmp_path: Path) -> None:
    service_root = tmp_path
    _make_service(service_root)

    from migrations.migrations_manager import MigrationsManager

    manager = MigrationsManager(service_root)
    result = manager.make()

    assert result.migration_file is not None
    migration_path = Path(result.migration_file)
    assert migration_path.exists()
    content = migration_path.read_text(encoding="utf-8")
    assert "def upgrade" in content
    assert "op.create_table(\n        'users'" in content
