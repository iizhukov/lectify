from pathlib import Path

from .models import MakeMigrationResult
from .schema_builder import SchemaBuilder
from .schema_comparator import SchemaComparator
from .migration_renderer import MigrationRenderer
from .migration_executor import MigrationExecutor
from .utils import SettingsLoader, MigrationFileUtils


class MigrationsManager:
    def __init__(self, service_root: Path):
        self.service_root = service_root.resolve()
        self.migrations_dir = self.service_root / "migrations"
        
        self.settings = SettingsLoader.load_settings(service_root)
        self.db_url = self.settings.database.url
        
        self.schema_builder = SchemaBuilder(service_root)
        self.schema_comparator = SchemaComparator()
        self.migration_renderer = MigrationRenderer()
        self.migration_executor = MigrationExecutor(self.db_url, self.migrations_dir)
        
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        self.migrations_dir.mkdir(parents=True, exist_ok=True)
        (self.migrations_dir / "versions").mkdir(parents=True, exist_ok=True)
    
    def make(self, message: str = None) -> MakeMigrationResult:
        print("[make] Starting migration generation...")
        
        self.schema_builder.clear_cache()
        
        migration_schema = self.schema_builder.build_from_migrations()
        model_schema = self.schema_builder.build_from_models()
        
        if not model_schema:
            return MakeMigrationResult(error="No models found")
        
        diff = self.schema_comparator.diff_schemas(migration_schema, model_schema)
        
        if not diff:
            return MakeMigrationResult(changes=[], message="No changes detected")
        
        rev_id = MigrationFileUtils.get_next_revision_id(self.migrations_dir)
        head_revision = MigrationFileUtils.find_head_revision(self.migrations_dir)
        
        if message is None:
            message = self.schema_comparator.generate_message(diff)
        
        versions_dir = self.migrations_dir / "versions"
        migration_path = versions_dir / f"{rev_id}_{message}.py"
        
        content = self.migration_renderer.render(
            diff, rev_id, head_revision, message,
            migration_schema, model_schema
        )
        migration_path.write_text(content)
        
        print(f"[make] Created: {migration_path.name}")
        
        return MakeMigrationResult(
            migration_file=str(migration_path),
            revision=rev_id,
            changes=diff
        )
    
    async def migrate(self) -> dict:
        result = await self.migration_executor.migrate()
        return {
            "applied": result.applied,
            "skipped": result.skipped,
            "errors": result.errors
        }
    
    async def rollback(self, steps: int = 1) -> dict:
        return await self.migration_executor.rollback(steps)
    
    async def status(self) -> dict:
        return await self.migration_executor.status()


def get_migrations_manager(service_root: Path) -> MigrationsManager:
    return MigrationsManager(service_root)
