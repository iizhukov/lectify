import re
import sys

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .finder import ModelFinder


_MIGRATIONS_TABLE = "_migrations"

TYPE_NORMALIZE = {
    "INTEGER": "INTEGER", "INT": "INTEGER",
    "BIGINTEGER": "BIGINTEGER", "BIGINT": "BIGINTEGER",
    "SMALLINTEGER": "SMALLINTEGER", "SMALLINT": "SMALLINTEGER",
    "VARCHAR": "VARCHAR", "STRING": "VARCHAR",
    "CHAR": "CHAR", "TEXT": "TEXT",
    "BOOLEAN": "BOOLEAN", "BOOL": "BOOLEAN",
    "DATETIME": "DATETIME", "DATE": "DATE", "TIME": "TIME",
    "FLOAT": "FLOAT", "NUMERIC": "NUMERIC", "DECIMAL": "NUMERIC",
    "UUID": "UUID", "JSON": "JSON", "JSONB": "JSONB",
}


class MigrationsManager:
    def __init__(self, service_root: Path):
        self.service_root = service_root.resolve()
        self.migrations_dir = self.service_root / "migrations"

        if str(self.service_root) not in sys.path:
            sys.path.insert(0, str(self.service_root))

        self.settings = self._load_settings()
        self.db_url = self.settings.database.url
        
        self.migrations_dir.mkdir(parents=True, exist_ok=True)
        (self.migrations_dir / "versions").mkdir(parents=True, exist_ok=True)
        
        self._model_schema_cache = None
        self._migration_schema_cache = None
    
    def _load_settings(self):
        try:
            from generated.settings import get_settings
            return get_settings()
        except ImportError:
            print("[manager] Cannot import get_settings")
            raise
    
    def _normalize_type(self, type_str: str) -> str:
        type_str = str(type_str).strip().upper()
        match = re.match(r"(\w+)\((\d+(?:,\d+)?)\)", type_str)

        if match:
            base = match.group(1)
            params = match.group(2)
            normalized_base = TYPE_NORMALIZE.get(base, base)

            return f"{normalized_base}({params})"
        
        return TYPE_NORMALIZE.get(type_str, type_str)
    
    def _get_sa_type(self, type_str: str) -> str:
        clean = type_str.upper()
        match = re.match(r"(\w+)\((\d+(?:,\d+)?)\)", clean)

        if match:
            base = match.group(1)
            params = match.group(2)
            sa_base = self._sa_type_map(base)

            return f"sa.{sa_base}({params})"
        
        sa_base = self._sa_type_map(clean)
        return f"sa.{sa_base}"
    
    def _sa_type_map(self, type_name: str) -> str:
        mapping = {
            "INTEGER": "Integer", "BIGINTEGER": "BigInteger", "SMALLINTEGER": "SmallInteger",
            "VARCHAR": "String", "CHAR": "String", "TEXT": "Text",
            "BOOLEAN": "Boolean", "DATETIME": "DateTime", "DATE": "Date", "TIME": "Time",
            "FLOAT": "Float", "NUMERIC": "Numeric", "UUID": "Uuid", "JSON": "JSON", "JSONB": "JSONB",
        }
        return mapping.get(type_name, type_name.capitalize())
    
    def _get_next_revision_id(self) -> str:
        versions_dir = self.migrations_dir / "versions"
        if not versions_dir.exists():
            return "0001"
        existing = []
        for path in versions_dir.glob("*.py"):
            if path.stem == "__init__":
                continue
            match = re.match(r"^(\d{4})_", path.stem)
            if match:
                existing.append(int(match.group(1)))
        return f"{max(existing) + 1:04d}" if existing else "0001"
    
    def _find_head_revision(self) -> Optional[str]:
        versions_dir = self.migrations_dir / "versions"
        if not versions_dir.exists():
            return None
        revisions = sorted([
            p for p in versions_dir.glob("*.py")
            if p.stem != "__init__" and re.match(r"^\d{4}_", p.stem)
        ])
        if not revisions:
            return None
        content = revisions[-1].read_text()
        match = re.search(r"revision:\s*str\s*=\s*['\"](\w+)['\"]", content)
        return match.group(1) if match else None
    
    def _build_schema_from_models(self) -> dict[str, Any]:
        if self._model_schema_cache is not None:
            return self._model_schema_cache
        
        finder = ModelFinder(self.service_root)
        base_class = finder.find_base_class()
        if base_class is None:
            return {}
        
        finder.get_metadata(base_class)
        
        schema = {}
        for table_name, table in base_class.metadata.tables.items():
            columns = []
            for col in table.columns:
                col_info = {
                    "name": col.name,
                    "type": self._normalize_type(str(col.type)),
                    "nullable": col.nullable,
                    "default": self._extract_default(col),
                }
                columns.append(col_info)
            schema[table_name] = {"columns": columns}
        
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
    
    def _build_schema_from_migrations(self) -> dict[str, Any]:
        if self._migration_schema_cache is not None:
            return self._migration_schema_cache
        
        schema = {}
        versions_dir = self.migrations_dir / "versions"
        
        if not versions_dir.exists():
            self._migration_schema_cache = schema
            return schema
        
        migration_files = []
        for path in versions_dir.glob("*.py"):
            if path.stem == "__init__":
                continue
            match = re.match(r"^(\d{4})_", path.stem)
            if match:
                migration_files.append((int(match.group(1)), path))
        
        migration_files.sort()
        
        print(f"[make] Processing {len(migration_files)} migrations...")
        
        for seq, path in migration_files:
            try:
                content = path.read_text()
                migration_schema = self._parse_migration(content)
                schema = self._merge_schemas(schema, migration_schema)
                print(f"[make] Applied: {path.stem}")
            except Exception as e:
                print(f"[make] Error parsing {path.stem}: {e}")
        
        print(f"[make] Migration schema has {len(schema)} tables")
        for table_name, table_info in schema.items():
            col_names = [f"{c['name']}({c['type']})" for c in table_info["columns"]]
            print(f"[make]   {table_name}: {col_names}")
        
        self._migration_schema_cache = schema
        return schema
    
    def _parse_migration(self, content: str) -> dict[str, Any]:
        schema = {}
        
        upgrade_match = re.search(r'def upgrade\(\) -> None:(.*?)(?=def downgrade)', content, re.DOTALL)
        if not upgrade_match:
            return schema
        
        upgrade_body = upgrade_match.group(1)
        
        self._parse_drop_table(upgrade_body, schema)
        self._parse_drop_column(upgrade_body, schema)
        self._parse_create_table(upgrade_body, schema)
        self._parse_add_column(upgrade_body, schema)
        self._parse_alter_column(upgrade_body, schema)
        
        for table_info in schema.values():
            for col in table_info.get("columns", []):
                col["type"] = self._normalize_type(col["type"])
        
        return schema
    
    def _parse_drop_table(self, upgrade_body: str, schema: dict) -> None:
        drop_pattern = r'op\.drop_table\(\s*[\'"]([\w]+)[\'"]\s*\)'
        for match in re.finditer(drop_pattern, upgrade_body):
            table_name = match.group(1).lower()
            schema.pop(table_name, None)
            schema[table_name] = {"columns": [], "_dropped_table": True}
            print(f"[parser] DROP TABLE {table_name}")
    
    def _parse_drop_column(self, upgrade_body: str, schema: dict) -> None:
        drop_col_pattern = r'op\.drop_column\(\s*[\'"]([\w]+)[\'"],\s*[\'"]([\w]+)[\'"]\s*\)'
        for match in re.finditer(drop_col_pattern, upgrade_body):
            table_name = match.group(1).lower()
            col_name = match.group(2).lower()
            
            if table_name in schema and not schema[table_name].get("_dropped_table"):
                before = len(schema[table_name].get("columns", []))
                schema[table_name]["columns"] = [
                    c for c in schema[table_name].get("columns", [])
                    if c["name"] != col_name
                ]
                after = len(schema[table_name]["columns"])
                if before != after:
                    print(f"[parser] DROP COLUMN {table_name}.{col_name}")
            else:
                # Таблицы нет в текущей схеме - отмечаем для мержа
                if table_name not in schema:
                    schema[table_name] = {"columns": []}
                dropped = schema[table_name].setdefault("_dropped_columns", [])
                if col_name not in dropped:
                    dropped.append(col_name)
                print(f"[parser] DROP COLUMN {table_name}.{col_name} (deferred)")
    
    def _parse_create_table(self, upgrade_body: str, schema: dict) -> None:
        create_pattern = r'op\.create_table\(\s*[\'"]([\w]+)[\'"],\s*(.*?)(?=\n\s*(?:op\.\w+\(|\)\s*$))'
        for match in re.finditer(create_pattern, upgrade_body, re.DOTALL):
            table_name = match.group(1).lower()
            table_body = match.group(2)
            columns = self._extract_columns_from_body(table_body)
            if columns:
                schema[table_name] = {"columns": columns}
                print(f"[parser] CREATE TABLE {table_name} ({len(columns)} cols)")
    
    def _extract_columns_from_body(self, body: str) -> list[dict]:
        columns = []
        col_pattern = r'sa\.Column\(\s*[\'"]([\w]+)[\'"],\s*sa\.(\w+(?:\(\d+(?:,\d+)?\))?)'
        
        for col_match in re.finditer(col_pattern, body):
            col_name = col_match.group(1).lower()
            col_type = col_match.group(2)
            
            depth = 0
            end_pos = col_match.end()
            for i in range(col_match.end(), len(body)):
                if body[i] == '(':
                    depth += 1
                elif body[i] == ')':
                    if depth == 0:
                        end_pos = i + 1
                        break
                    depth -= 1
            
            col_str = body[col_match.start():end_pos]
            nullable = 'nullable=False' not in col_str
            
            default = None
            default_match = re.search(r"server_default=['\"]([^'\"]*)['\"]", col_str)
            if default_match:
                default = default_match.group(1)
            
            columns.append({
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
                "default": default,
            })
        
        return columns
    
    def _parse_add_column(self, upgrade_body: str, schema: dict) -> None:
        add_col_pattern = r'op\.add_column\(\s*[\'"]([\w]+)[\'"],\s*sa\.Column\(\s*[\'"]([\w]+)[\'"],\s*sa\.(\w+(?:\(\d+(?:,\d+)?\))?)'
        
        for match in re.finditer(add_col_pattern, upgrade_body):
            table_name = match.group(1).lower()
            col_name = match.group(2).lower()
            col_type = match.group(3)
            
            depth = 0
            end_pos = match.end()
            for i in range(match.end(), len(upgrade_body)):
                if upgrade_body[i] == '(':
                    depth += 1
                elif upgrade_body[i] == ')':
                    if depth == 0:
                        end_pos = i + 1
                        break
                    depth -= 1
            
            col_str = upgrade_body[match.start():end_pos]
            nullable = 'nullable=False' not in col_str
            
            default = None
            default_match = re.search(r"server_default=['\"]([^'\"]*)['\"]", col_str)
            if default_match:
                default = default_match.group(1)
            
            if table_name not in schema:
                schema[table_name] = {"columns": []}
            
            if not any(c["name"] == col_name for c in schema[table_name].get("columns", [])):
                schema[table_name].setdefault("columns", []).append({
                    "name": col_name,
                    "type": col_type,
                    "nullable": nullable,
                    "default": default,
                })
                print(f"[parser] ADD COLUMN {table_name}.{col_name} {col_type}")
    
    def _parse_alter_column(self, upgrade_body: str, schema: dict) -> None:
        alter_pattern = r'op\.alter_column\(\s*[\'"]([\w]+)[\'"],\s*[\'"]([\w]+)[\'"]'
        
        for match in re.finditer(alter_pattern, upgrade_body):
            table_name = match.group(1).lower()
            col_name = match.group(2).lower()
            
            line_start = max(0, match.start() - 50)
            line_end = min(len(upgrade_body), match.end() + 300)
            context_str = upgrade_body[line_start:line_end]
            
            if table_name in schema:
                for col in schema[table_name].get("columns", []):
                    if col["name"] == col_name:
                        type_match = re.search(r'type_=sa\.(\w+(?:\(\d+(?:,\d+)?\))?)', context_str)
                        if type_match:
                            col["type"] = type_match.group(1)
                        if 'nullable=False' in context_str:
                            col["nullable"] = False
                        elif 'nullable=True' in context_str:
                            col["nullable"] = True
                        break
    
    def _merge_schemas(self, base: dict, new: dict) -> dict:
        result = {k: {"columns": [c.copy() for c in v.get("columns", [])]} 
                  for k, v in base.items() if not v.get("_dropped_table")}
        
        for table_name, table_info in new.items():
            # Обрабатываем удалённые таблицы
            if table_info.get("_dropped_table"):
                result.pop(table_name, None)
                continue
            
            # Обрабатываем удалённые колонки
            dropped = table_info.get("_dropped_columns", [])
            if dropped and table_name in result:
                for col_name in dropped:
                    result[table_name]["columns"] = [
                        c for c in result[table_name]["columns"]
                        if c["name"] != col_name
                    ]
            
            # Обрабатываем добавленные колонки
            if table_name not in result:
                result[table_name] = {"columns": [c.copy() for c in table_info.get("columns", [])]}
            else:
                existing = {c["name"]: c for c in result[table_name]["columns"]}
                for new_col in table_info.get("columns", []):
                    if new_col["name"] not in existing:
                        result[table_name]["columns"].append(new_col.copy())
                    else:
                        existing[new_col["name"]].update(new_col)
            
            # Убираем служебные поля
            result[table_name].pop("_dropped_columns", None)
            result[table_name].pop("_dropped_table", None)
        
        return result
    
    def _generate_message(self, diff: list[str]) -> str:
        actions = []
        for op in diff:
            action = op.split(":")[0]
            if action == "create_table":
                actions.append(f"add_{op.split(':')[1]}")
            elif action == "drop_table":
                actions.append(f"drop_{op.split(':')[1]}")
            elif action == "add_column":
                parts = op.split(":")
                actions.append(f"add_{parts[2]}_to_{parts[1]}")
            elif action == "drop_column":
                parts = op.split(":")
                actions.append(f"drop_{parts[2]}_from_{parts[1]}")
            elif action == "alter_column":
                parts = op.split(":")
                actions.append(f"alter_{parts[2]}_in_{parts[1]}")
        
        if not actions:
            return "update_schema"
        if len(actions) == 1:
            return actions[0][:60]
        if len(actions) > 2:
            result = f"{'_'.join(actions[:2])}_and_{len(actions)-2}_more"
        else:
            result = "_".join(actions)
        return result[:60]
    
    def make(self, message: str = None) -> dict[str, Any]:
        print("[make] Starting migration generation...")
        
        self._model_schema_cache = None
        self._migration_schema_cache = None
        
        migration_schema = self._build_schema_from_migrations()
        model_schema = self._build_schema_from_models()
        
        if not model_schema:
            return {"migration_file": None, "error": "No models found"}
        
        diff = self._diff_schemas(migration_schema, model_schema)
        
        if not diff:
            return {"migration_file": None, "changes": [], "message": "No changes detected"}
        
        rev_id = self._get_next_revision_id()
        head_revision = self._find_head_revision()
        
        if message is None:
            message = self._generate_message(diff)
        
        versions_dir = self.migrations_dir / "versions"
        migration_path = versions_dir / f"{rev_id}_{message}.py"
        
        content = self._render_migration(diff, rev_id, head_revision, message, migration_schema, model_schema)
        migration_path.write_text(content)
        
        print(f"[make] Created: {migration_path.name}")
        return {"migration_file": str(migration_path), "revision": rev_id, "changes": diff}
    
    def _diff_schemas(self, source: dict, target: dict) -> list[str]:
        ops = []
        
        source_tables = set(source.keys())
        target_tables = set(target.keys())
        
        for table in sorted(target_tables - source_tables):
            ops.append(f"create_table:{table}")
        for table in sorted(source_tables - target_tables):
            ops.append(f"drop_table:{table}")
        for table in sorted(source_tables & target_tables):
            source_cols = {c["name"]: c for c in source[table]["columns"]}
            target_cols = {c["name"]: c for c in target[table]["columns"]}
            
            for col in sorted(set(target_cols.keys()) - set(source_cols.keys())):
                ops.append(f"add_column:{table}:{col}")
            for col in sorted(set(source_cols.keys()) - set(target_cols.keys())):
                ops.append(f"drop_column:{table}:{col}")
            for col in sorted(set(source_cols.keys()) & set(target_cols.keys())):
                source_col = source_cols[col]
                target_col = target_cols[col]
                if (source_col["type"] != target_col["type"] or
                    source_col["nullable"] != target_col["nullable"] or
                    source_col.get("default") != target_col.get("default")):
                    ops.append(f"alter_column:{table}:{col}")
        
        return ops
    
    def _render_migration(self, ops: list[str], rev_id: str, head_revision: Optional[str],
                         message: str, migration_schema: dict, model_schema: dict) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        
        upgrade_lines = []
        downgrade_lines = []
        
        for op in ops:
            parts = op.split(":")
            action = parts[0]
            
            if action == "create_table":
                table = parts[1]
                col_defs = self._get_sa_column_defs(table, model_schema)
                if col_defs:
                    columns_str = ",\n        ".join(col_defs)
                    upgrade_lines.append(f"    op.create_table(\n        '{table}',\n        {columns_str}\n    )")
                    downgrade_lines.append(f"    op.drop_table('{table}')")
            
            elif action == "drop_table":
                table = parts[1]
                if table in migration_schema:
                    col_defs = self._get_sa_column_defs(table, migration_schema)
                    if col_defs:
                        columns_str = ",\n        ".join(col_defs)
                        downgrade_lines.append(f"    op.create_table(\n        '{table}',\n        {columns_str}\n    )")
                upgrade_lines.append(f"    op.drop_table('{table}')")
            
            elif action == "add_column":
                table, col = parts[1], parts[2]
                col_info = self._get_column_info_from_schema(table, col, model_schema)
                if col_info:
                    col_def = f"sa.Column('{col}', {col_info['type']}"
                    if not col_info['nullable']:
                        col_def += ", nullable=False"
                    if col_info.get('default'):
                        col_def += f", server_default='{col_info['default']}'"
                    col_def += ")"
                    upgrade_lines.append(f"    op.add_column('{table}', {col_def})")
                    downgrade_lines.append(f"    op.drop_column('{table}', '{col}')")
            
            elif action == "drop_column":
                table, col = parts[1], parts[2]
                old_info = self._get_column_info_from_schema(table, col, migration_schema)
                if old_info:
                    col_def = f"sa.Column('{col}', {old_info['type']}"
                    if not old_info['nullable']:
                        col_def += ", nullable=False"
                    if old_info.get('default'):
                        col_def += f", server_default='{old_info['default']}'"
                    col_def += ")"
                    downgrade_lines.append(f"    op.add_column('{table}', {col_def})")
                upgrade_lines.append(f"    op.drop_column('{table}', '{col}')")
            
            elif action == "alter_column":
                table, col = parts[1], parts[2]
                old_info = self._get_column_info_from_schema(table, col, migration_schema)
                new_info = self._get_column_info_from_schema(table, col, model_schema)
                
                if old_info and new_info:
                    if old_info['type'] != new_info['type']:
                        upgrade_lines.append(
                            f"    op.alter_column('{table}', '{col}',\n"
                            f"        existing_type={old_info['type']},\n"
                            f"        type_={new_info['type']})"
                        )
                        downgrade_lines.append(
                            f"    op.alter_column('{table}', '{col}',\n"
                            f"        existing_type={new_info['type']},\n"
                            f"        type_={old_info['type']})"
                        )
                    if old_info['nullable'] != new_info['nullable']:
                        current_type = new_info['type'] if old_info['type'] != new_info['type'] else old_info['type']
                        upgrade_lines.append(
                            f"    op.alter_column('{table}', '{col}',\n"
                            f"        existing_type={current_type},\n"
                            f"        nullable={new_info['nullable']})"
                        )
                        downgrade_lines.append(
                            f"    op.alter_column('{table}', '{col}',\n"
                            f"        existing_type={current_type},\n"
                            f"        nullable={old_info['nullable']})"
                        )
        
        upgrade_str = "\n".join(upgrade_lines) if upgrade_lines else "    pass"
        downgrade_str = "\n".join(reversed(downgrade_lines)) if downgrade_lines else "    pass"
        
        return f'''"""{message}

Revision ID: {rev_id}
Revises: {head_revision or "None"}
Create Date: {now}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '{rev_id}'
down_revision: Union[str, None] = {repr(head_revision) if head_revision else "None"}
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
{upgrade_str}


def downgrade() -> None:
{downgrade_str}
'''
    
    def _get_sa_column_defs(self, table_name: str, schema: dict) -> list[str]:
        if table_name not in schema:
            return []
        defs = []
        for col in schema[table_name]["columns"]:
            sa_type = self._get_sa_type(col['type'])
            col_str = f"sa.Column('{col['name']}', {sa_type}"
            if not col['nullable']:
                col_str += ", nullable=False"
            if col.get('default'):
                col_str += f", server_default='{col['default']}'"
            col_str += ")"
            defs.append(col_str)
        return defs
    
    def _get_column_info_from_schema(self, table_name: str, col_name: str, schema: dict) -> Optional[dict]:
        if table_name not in schema:
            return None
        for col in schema[table_name]["columns"]:
            if col["name"] == col_name:
                return {
                    "type": self._get_sa_type(col['type']),
                    "nullable": col['nullable'],
                    "default": col.get('default'),
                }
        return None
    
    async def status(self) -> dict[str, Any]:
        engine = create_async_engine(self.db_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :table)"),
                    {"table": _MIGRATIONS_TABLE}
                )
                exists = result.scalar()
                
                if not exists:
                    await conn.execute(
                        text(f"CREATE TABLE {_MIGRATIONS_TABLE} (id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE, applied_at TIMESTAMP DEFAULT NOW())")
                    )
                    await conn.commit()
                    applied = set()
                else:
                    result = await conn.execute(text(f"SELECT name FROM {_MIGRATIONS_TABLE} ORDER BY id"))
                    applied = {row[0] for row in result}
                
                versions_dir = self.migrations_dir / "versions"
                all_migrations = []
                
                if versions_dir.exists():
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
                        all_migrations.append({
                            "name": name, "sequence": sequence,
                            "revision": revision, "description": description,
                            "applied": name in applied,
                        })
                
                return {
                    "migrations_dir": str(self.migrations_dir),
                    "total": len(all_migrations),
                    "applied_count": len([m for m in all_migrations if m["applied"]]),
                    "pending_count": len([m for m in all_migrations if not m["applied"]]),
                    "migrations": all_migrations,
                }
        finally:
            await engine.dispose()
    
    def _get_alembic_config(self) -> Any:
        from alembic.config import Config
        sync_url = self.db_url.replace("+asyncpg", "+psycopg2")
        
        alembic_ini = self.service_root / "alembic.ini"
        alembic_ini.write_text(f"""[alembic]
script_location = {self.migrations_dir}
sqlalchemy.url = {sync_url}

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
""")
        return Config(str(alembic_ini))
    
    def _ensure_env_py(self):
        env_py = self.migrations_dir / "env.py"
        if not env_py.exists():
            env_py.write_text("""from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
""")
    
    async def migrate(self) -> dict[str, Any]:
        from alembic import command
        engine = create_async_engine(self.db_url)
        applied, skipped, errors = [], [], []
        
        try:
            async with engine.connect() as conn:
                await conn.execute(
                    text(f"CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} "
                         f"(id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE, "
                         f"applied_at TIMESTAMP DEFAULT NOW())")
                )
                await conn.commit()
                
                result = await conn.execute(text(f"SELECT name FROM {_MIGRATIONS_TABLE} ORDER BY id"))
                applied_names = {row[0] for row in result}
                
                versions_dir = self.migrations_dir / "versions"
                if not versions_dir.exists():
                    return {"applied": [], "skipped": [], "errors": []}
                
                migration_files = []
                for path in versions_dir.glob("*.py"):
                    if path.stem == "__init__":
                        continue
                    match = re.match(r"^(\d{4})_", path.stem)
                    if match:
                        migration_files.append((int(match.group(1)), path))
                migration_files.sort()
                
                self._ensure_env_py()
                alembic_cfg = self._get_alembic_config()
                
                for seq, path in migration_files:
                    name = path.stem
                    if name in applied_names:
                        skipped.append(name)
                        continue
                    try:
                        print(f"[migrate] Applying: {name}")
                        content = path.read_text()
                        rev_match = re.search(r"revision:\s*str\s*=\s*['\"](\w+)['\"]", content)
                        if rev_match:
                            command.upgrade(alembic_cfg, rev_match.group(1))
                        else:
                            command.upgrade(alembic_cfg, "head")
                        
                        await conn.execute(
                            text(f"INSERT INTO {_MIGRATIONS_TABLE} (name) VALUES (:name)"),
                            {"name": name}
                        )
                        await conn.commit()
                        applied.append(name)
                        print(f"[migrate] Applied: {name}")
                    except Exception as e:
                        errors.append({"migration": name, "error": str(e)})
                        print(f"[migrate] Error: {e}")
                        break
                
                return {"applied": applied, "skipped": skipped, "errors": errors}
        finally:
            await engine.dispose()
    
    async def rollback(self, steps: int = 1) -> dict[str, Any]:
        from alembic import command
        engine = create_async_engine(self.db_url)
        rolled_back, errors = [], []
        
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(f"SELECT name FROM {_MIGRATIONS_TABLE} ORDER BY id DESC LIMIT :limit"),
                    {"limit": steps}
                )
                to_rollback = [row[0] for row in result]
                
                if not to_rollback:
                    return {"rolled_back": [], "errors": [], "message": "No migrations to rollback"}
                
                self._ensure_env_py()
                alembic_cfg = self._get_alembic_config()
                
                for name in to_rollback:
                    try:
                        path = self.migrations_dir / "versions" / f"{name}.py"
                        if not path.exists():
                            errors.append({"migration": name, "error": "File not found"})
                            continue
                        
                        print(f"[rollback] Rolling back: {name}")
                        content = path.read_text()
                        down_match = re.search(r"down_revision.*?=\s*['\"](\w+)['\"]", content)
                        
                        if down_match and down_match.group(1) != "None":
                            command.downgrade(alembic_cfg, down_match.group(1))
                        else:
                            command.downgrade(alembic_cfg, "-1")
                        
                        await conn.execute(
                            text(f"DELETE FROM {_MIGRATIONS_TABLE} WHERE name = :name"),
                            {"name": name}
                        )
                        await conn.commit()
                        rolled_back.append(name)
                        print(f"[rollback] Rolled back: {name}")
                    except Exception as e:
                        errors.append({"migration": name, "error": str(e)})
                        print(f"[rollback] Error: {e}")
                        break
                
                return {"rolled_back": rolled_back, "errors": errors}
        finally:
            await engine.dispose()


def get_migrations_manager(service_root: Path) -> MigrationsManager:
    return MigrationsManager(service_root)
