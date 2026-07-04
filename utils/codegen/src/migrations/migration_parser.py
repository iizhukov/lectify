import re
from typing import Dict

from .models import TableSchema, ColumnInfo
from .patterns import MigrationPatterns
from .utils import TypeNormalizer


class MigrationParser:
    def __init__(self):
        self.patterns = MigrationPatterns()
        self.type_normalizer = TypeNormalizer()
    
    def parse(self, content: str) -> Dict[str, TableSchema]:
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
        
        for table_schema in schema.values():
            for col in table_schema.columns:
                col.type = self.type_normalizer.normalize_type(col.type)
        
        return schema
    
    def _parse_drop_table(self, upgrade_body: str, schema: Dict[str, TableSchema]) -> None:
        for match in self.patterns.DROP_TABLE.finditer(upgrade_body):
            table_name = match.group(1).lower()
            schema[table_name] = TableSchema(is_dropped=True)
            print(f"[parser] DROP TABLE {table_name}")
    
    def _parse_drop_column(self, upgrade_body: str, schema: Dict[str, TableSchema]) -> None:
        for match in self.patterns.DROP_COLUMN.finditer(upgrade_body):
            table_name = match.group(1).lower()
            col_name = match.group(2).lower()
            
            if table_name in schema and not schema[table_name].is_dropped:
                before = len(schema[table_name].columns)
                schema[table_name].columns = [
                    c for c in schema[table_name].columns
                    if c.name != col_name
                ]

                after = len(schema[table_name].columns)
                if before != after:
                    print(f"[parser] DROP COLUMN {table_name}.{col_name}")
            else:
                if table_name not in schema:
                    schema[table_name] = TableSchema()

                if col_name not in schema[table_name].dropped_columns:
                    schema[table_name].dropped_columns.append(col_name)

                print(f"[parser] DROP COLUMN {table_name}.{col_name} (deferred)")
    
    def _parse_create_table(self, upgrade_body: str, schema: Dict[str, TableSchema]) -> None:
        for match in self.patterns.CREATE_TABLE.finditer(upgrade_body):
            table_name = match.group(1).lower()
            table_body = match.group(2)
            columns = self._extract_columns(table_body)

            if columns:
                schema[table_name] = TableSchema(columns=columns)
                print(f"[parser] CREATE TABLE {table_name} ({len(columns)} cols)")
    
    def _parse_add_column(self, upgrade_body: str, schema: Dict[str, TableSchema]) -> None:
        for match in self.patterns.ADD_COLUMN.finditer(upgrade_body):
            table_name = match.group(1).lower()
            col_name = match.group(2).lower()
            col_type = match.group(3)
            
            col_str = self._extract_column_string(upgrade_body, match)
            col_info = self._parse_column_info(col_name, col_type, col_str)
            
            if table_name not in schema:
                schema[table_name] = TableSchema()
            
            if not any(c.name == col_name for c in schema[table_name].columns):
                schema[table_name].columns.append(col_info)
                print(f"[parser] ADD COLUMN {table_name}.{col_name} {col_type}")
    
    def _parse_alter_column(self, upgrade_body: str, schema: Dict[str, TableSchema]) -> None:
        for match in self.patterns.ALTER_COLUMN.finditer(upgrade_body):
            table_name = match.group(1).lower()
            col_name = match.group(2).lower()
            
            if table_name not in schema:
                continue
            
            context_str = self._extract_context(upgrade_body, match)
            
            for col in schema[table_name].columns:
                if col.name == col_name:
                    self._update_column_info(col, context_str)
                    break
    
    def _extract_columns(self, body: str) -> list:
        columns = []
        for col_match in self.patterns.COLUMN_DEFINITION.finditer(body):
            col_name = col_match.group(1).lower()
            col_type = col_match.group(2)
            
            col_str = self._extract_column_string(body, col_match)
            col_info = self._parse_column_info(col_name, col_type, col_str)
            columns.append(col_info)
        
        return columns
    
    def _extract_column_string(self, body: str, match: re.Match) -> str:
        depth = 0
        end_pos = match.end()

        for i in range(match.end(), len(body)):
            if body[i] == '(':
                depth += 1
            elif body[i] == ')':
                if depth == 0:
                    end_pos = i + 1
                    break

                depth -= 1

        return body[match.start():end_pos]
    
    def _parse_column_info(self, col_name: str, col_type: str, col_str: str) -> ColumnInfo:
        nullable = 'nullable=False' not in col_str
        
        default = None
        default_match = re.search(r"server_default=['\"]([^'\"]*)['\"]", col_str)
        if default_match:
            default = default_match.group(1)
        
        return ColumnInfo(
            name=col_name,
            type=col_type,
            nullable=nullable,
            default=default
        )
    
    def _extract_context(self, upgrade_body: str, match: re.Match) -> str:
        line_start = max(0, match.start() - 50)
        line_end = min(len(upgrade_body), match.end() + 300)
        return upgrade_body[line_start:line_end]
    
    def _update_column_info(self, col: ColumnInfo, context: str) -> None:
        type_match = re.search(r'type_=sa\.(\w+(?:\(\d+(?:,\d+)?\))?)', context)
        if type_match:
            col.type = type_match.group(1)
        
        if 'nullable=False' in context:
            col.nullable = False
        elif 'nullable=True' in context:
            col.nullable = True
