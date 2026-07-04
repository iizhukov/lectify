from pathlib import Path
from typing import Optional, Dict, List

from migrations.models import TableSchema, ColumnInfo
from migrations.utils import TypeNormalizer, MigrationFileUtils
from migrations.migration_parser import MigrationParser
from migrations.finder import ModelFinder


class SchemaBuilder:
    def __init__(self, service_root: Path):
        self.service_root = service_root
        self.migrations_dir = service_root / "migrations"
        self._model_schema_cache: Optional[Dict[str, TableSchema]] = None
        self._migration_schema_cache: Optional[Dict[str, TableSchema]] = None
        self.type_normalizer = TypeNormalizer()
        self.migration_parser = MigrationParser()
    
    def build_from_models(self) -> Dict[str, TableSchema]:
        if self._model_schema_cache is not None:
            return self._model_schema_cache
        
        finder = ModelFinder(self.service_root)
        base_class = finder.find_base_class()
        
        if base_class is None:
            self._model_schema_cache = {}
            return {}
        
        finder.get_metadata(base_class)
        
        schema = {}
        for table_name, table in base_class.metadata.tables.items():
            columns = []
            for col in table.columns:
                col_info = ColumnInfo(
                    name=col.name,
                    type=self.type_normalizer.normalize_type(str(col.type)),
                    nullable=col.nullable,
                    default=self._extract_default(col)
                )
                columns.append(col_info)
            schema[table_name] = TableSchema(columns=columns)
        
        self._model_schema_cache = schema
        return schema
    
    def _extract_default(self, column) -> Optional[str]:
        if column.default is None and column.server_default is None:
            return None
        
        if column.server_default is not None:
            if hasattr(column.server_default, 'arg'):
                arg = column.server_default.arg

                if callable(arg):
                    return str(arg).lower()
                
                return str(arg)
            
            return str(column.server_default)
        
        if hasattr(column.default, 'arg'):
            arg = column.default.arg
            
            if callable(arg):
                return None
            
            if isinstance(arg, bool):
                return str(arg)
            
            if isinstance(arg, str):
                return arg
            
            return str(arg)
        
        return None
    
    def build_from_migrations(self) -> Dict[str, TableSchema]:
        if self._migration_schema_cache is not None:
            return self._migration_schema_cache
        
        schema = {}
        versions_dir = self.migrations_dir / "versions"
        
        if not versions_dir.exists():
            self._migration_schema_cache = schema
            return schema
        
        migration_files = self._get_migration_files(versions_dir)
        
        print(f"[make] Processing {len(migration_files)} migrations...")
        
        for seq, path in migration_files:
            try:
                content = path.read_text()
                migration_schema = self.migration_parser.parse(content)
                schema = self._merge_schemas(schema, migration_schema)
                print(f"[make] Applied: {path.stem}")
            except Exception as e:
                print(f"[make] Error parsing {path.stem}: {e}")
        
        self._log_schema_info(schema)
        self._migration_schema_cache = schema
        return schema
    
    def _get_migration_files(self, versions_dir: Path) -> List[tuple]:
        migration_files = []
        for path in versions_dir.glob("*.py"):
            if path.stem == "__init__":
                continue

            match = MigrationFileUtils.parse_migration_name(path.stem)

            if match:
                migration_files.append((match[0], path))

        return sorted(migration_files)
    
    def _merge_schemas(self, base: Dict[str, TableSchema], 
                       new: Dict[str, TableSchema]) -> Dict[str, TableSchema]:
        result = {}
        
        for table_name, table_schema in base.items():
            if not table_schema.is_dropped:
                result[table_name] = TableSchema(
                    columns=[c for c in table_schema.columns]
                )
        
        for table_name, table_schema in new.items():
            if table_schema.is_dropped:
                result.pop(table_name, None)
                continue
            
            if table_schema.dropped_columns and table_name in result:
                result[table_name].columns = [
                    c for c in result[table_name].columns
                    if c.name not in table_schema.dropped_columns
                ]
            
            if table_name not in result:
                result[table_name] = TableSchema(
                    columns=[c for c in table_schema.columns]
                )
            else:
                existing_names = {c.name for c in result[table_name].columns}
                for new_col in table_schema.columns:
                    if new_col.name not in existing_names:
                        result[table_name].columns.append(new_col)
        
        return result
    
    def _log_schema_info(self, schema: Dict[str, TableSchema]) -> None:
        print(f"[make] Migration schema has {len(schema)} tables")

        for table_name, table_info in schema.items():
            col_names = [f"{c.name}({c.type})" for c in table_info.columns]
            print(f"[make]   {table_name}: {col_names}")
    
    def get_model_schema(self) -> Dict[str, TableSchema]:
        return self.build_from_models()
    
    def get_migration_schema(self) -> Dict[str, TableSchema]:
        return self.build_from_migrations()
    
    def clear_cache(self) -> None:
        self._model_schema_cache = None
        self._migration_schema_cache = None
