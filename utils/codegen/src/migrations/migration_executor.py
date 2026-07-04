import re

from pathlib import Path
from typing import Set, List, Dict, Any, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .constants import MIGRATIONS_TABLE
from .models import MigrationResult, MigrationInfo
from .alembic_helper import AlembicHelper
from .patterns import MigrationPatterns


class MigrationExecutor:
    def __init__(self, db_url: str, migrations_dir: Path):
        self.db_url = db_url
        self.migrations_dir = migrations_dir
        self.alembic_helper = AlembicHelper(migrations_dir, db_url)
    
    async def migrate(self) -> MigrationResult:
        result = MigrationResult()
        engine = create_async_engine(self.db_url)
        
        try:
            async with engine.connect() as conn:
                await self._ensure_migrations_table(conn)
                applied_names = await self._get_applied_migrations(conn)
                
                migration_files = self._get_migration_files()
                if not migration_files:
                    return result
                
                for _, path in migration_files:
                    name = path.stem
                    if name in applied_names:
                        result.skipped.append(name)
                        continue
                    
                    try:
                        await self._apply_migration(conn, path, name, result)
                    except Exception as e:
                        result.errors.append({"migration": name, "error": str(e)})
                        print(f"[migrate] Error: {e}")
                        break
        
        finally:
            await engine.dispose()
        
        return result
    
    async def rollback(self, steps: int = 1) -> Dict[str, Any]:
        rolled_back = []
        errors = []
        engine = create_async_engine(self.db_url)
        
        try:
            async with engine.connect() as conn:
                await self._ensure_migrations_table(conn)
                to_rollback = await self._get_migrations_to_rollback(conn, steps)
                
                if not to_rollback:
                    return {"rolled_back": [], "errors": [], "message": "No migrations to rollback"}
                
                for name in to_rollback:
                    try:
                        path = self.migrations_dir / "versions" / f"{name}.py"
                        if not path.exists():
                            errors.append({"migration": name, "error": "File not found"})
                            continue
                        
                        await self._apply_rollback(conn, path, name, rolled_back, errors)
                    except Exception as e:
                        errors.append({"migration": name, "error": str(e)})
                        print(f"[rollback] Error: {e}")
                        break
        
        finally:
            await engine.dispose()
        
        return {"rolled_back": rolled_back, "errors": errors}
    
    async def status(self) -> Dict[str, Any]:
        engine = create_async_engine(self.db_url)
        
        try:
            async with engine.connect() as conn:
                all_migrations = self._get_all_migrations()
                applied_names = await self._get_applied_migrations(conn)

                for migration in all_migrations:
                    if migration["name"] in applied_names:
                        migration["applied"] = True
                
                return {
                    "migrations_dir": str(self.migrations_dir),
                    "total": len(all_migrations),
                    "applied_count": len([m for m in all_migrations if m["applied"]]),
                    "pending_count": len([m for m in all_migrations if not m["applied"]]),
                    "migrations": all_migrations,
                }
        finally:
            await engine.dispose()
    
    async def _ensure_migrations_table(self, conn) -> None:
        await conn.execute(
            text(f"CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} "
                 f"(id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE, "
                 f"applied_at TIMESTAMP DEFAULT NOW())")
        )
        await conn.commit()
    
    async def _get_applied_migrations(self, conn) -> Set[str]:
        result = await conn.execute(text(f"SELECT name FROM {MIGRATIONS_TABLE} ORDER BY id"))
        return {row[0] for row in result}
    
    async def _get_migrations_to_rollback(self, conn, steps: int) -> List[str]:
        result = await conn.execute(
            text(f"SELECT name FROM {MIGRATIONS_TABLE} ORDER BY id DESC LIMIT :limit"),
            {"limit": steps}
        )
        return [row[0] for row in result]
    
    def _get_migration_files(self) -> List[Tuple[int, Path]]:
        versions_dir = self.migrations_dir / "versions"
        if not versions_dir.exists():
            return []
        
        migration_files = []
        for path in versions_dir.glob("*.py"):
            if path.stem == "__init__":
                continue

            match = re.match(r"^(\d{4})_", path.stem)

            if match:
                migration_files.append((int(match.group(1)), path))

        return sorted(migration_files)
    
    def _get_all_migrations(self) -> List[Dict[str, Any]]:
        all_migrations = []
        versions_dir = self.migrations_dir / "versions"
        
        if not versions_dir.exists():
            return all_migrations
        
        for path in sorted(versions_dir.glob("*.py")):
            if path.stem == "__init__":
                continue
            
            name = path.stem
            match = re.match(r"^(\d{4})_(.+)$", name)

            if match:
                sequence = int(match.group(1))
                revision = match.group(1)
                description = match.group(2).replace("_", " ")
            else:
                sequence = 0
                revision = name
                description = ""
            
            all_migrations.append(MigrationInfo(
                name=name,
                sequence=sequence,
                revision=revision,
                description=description,
                applied=False  # будет обновлено позже
            ).__dict__)
        
        return all_migrations
    
    async def _apply_migration(
        self,
        conn,
        path: Path,
        name: str, 
        result: MigrationResult
    ) -> None:
        print(f"[migrate] Applying: {name}")
        content = path.read_text()
        rev_match = MigrationPatterns.REVISION_ID.search(content)
        
        if rev_match:
            self.alembic_helper.upgrade(rev_match.group(1))
        else:
            self.alembic_helper.upgrade("head")
        
        await conn.execute(
            text(f"INSERT INTO {MIGRATIONS_TABLE} (name) VALUES (:name)"),
            {"name": name}
        )
        await conn.commit()
        result.applied.append(name)
        print(f"[migrate] Applied: {name}")
    
    async def _apply_rollback(
        self,
        conn,
        path: Path,
        name: str, 
        rolled_back: List[str],
        errors: List[dict]
    ) -> None:
        print(f"[rollback] Rolling back: {name}")
        content = path.read_text()
        down_match = MigrationPatterns.DOWN_REVISION.search(content)
        
        if down_match and down_match.group(1) != "None":
            self.alembic_helper.downgrade(down_match.group(1))
        else:
            self.alembic_helper.downgrade("-1")
        
        await conn.execute(
            text(f"DELETE FROM {MIGRATIONS_TABLE} WHERE name = :name"),
            {"name": name}
        )
        await conn.commit()
        rolled_back.append(name)
        print(f"[rollback] Rolled back: {name}")
