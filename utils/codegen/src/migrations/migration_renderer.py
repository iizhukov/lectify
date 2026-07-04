from datetime import datetime
from typing import Optional, Dict, List

from .models import TableSchema
from .utils import TypeNormalizer


class MigrationRenderer:
    def __init__(self):
        self.type_normalizer = TypeNormalizer()
    
    def render(
        self,
        ops: List[str],
        rev_id: str,
        head_revision: Optional[str],
        message: str,
        migration_schema: Dict[str, TableSchema], 
        model_schema: Dict[str, TableSchema]
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        
        upgrade_lines = []
        downgrade_lines = []
        
        for op in ops:
            self._process_operation(
                op,
                upgrade_lines,
                downgrade_lines, 
                migration_schema,
                model_schema
            )
        
        upgrade_str = self._format_operations(upgrade_lines)
        downgrade_str = self._format_operations(downgrade_lines)
        
        return self._render_template(
            message,
            rev_id,
            head_revision,
            now,
            upgrade_str,
            downgrade_str
        )
    
    def _process_operation(
        self,
        op: str,
        upgrade_lines: List[str], 
        downgrade_lines: List[str],
        migration_schema: Dict[str, TableSchema],
        model_schema: Dict[str, TableSchema]
    ) -> None:
        parts = op.split(":")
        action = parts[0]
        
        if action == "create_table":
            self._process_create_table(parts[1], upgrade_lines, downgrade_lines, model_schema)
        elif action == "drop_table":
            self._process_drop_table(parts[1], upgrade_lines, downgrade_lines, migration_schema)
        elif action == "add_column":
            self._process_add_column(parts[1], parts[2], upgrade_lines, downgrade_lines, model_schema)
        elif action == "drop_column":
            self._process_drop_column(parts[1], parts[2], upgrade_lines, downgrade_lines, migration_schema)
        elif action == "alter_column":
            self._process_alter_column(
                parts[1],
                parts[2],
                upgrade_lines,
                downgrade_lines, 
                migration_schema,
                model_schema
            )
    
    def _process_create_table(
        self,
        table: str,
        upgrade_lines: List[str],
        downgrade_lines: List[str], 
        schema: Dict[str, TableSchema]
    ) -> None:
        if table in schema:
            col_defs = self._get_column_definitions(table, schema)

            if col_defs:
                columns_str = ",\n        ".join(col_defs)
                upgrade_lines.append(f"    op.create_table(\n        '{table}',\n        {columns_str}\n    )")
                downgrade_lines.append(f"    op.drop_table('{table}')")
    
    def _process_drop_table(
        self,
        table: str,
        upgrade_lines: List[str],
        downgrade_lines: List[str],
        schema: Dict[str, TableSchema]
    ) -> None:
        upgrade_lines.append(f"    op.drop_table('{table}')")

        if table in schema:
            col_defs = self._get_column_definitions(table, schema)

            if col_defs:
                columns_str = ",\n        ".join(col_defs)
                downgrade_lines.append(f"    op.create_table(\n        '{table}',\n        {columns_str}\n    )")
    
    def _process_add_column(
        self,
        table: str,
        col: str,
        upgrade_lines: List[str],
        downgrade_lines: List[str],
        schema: Dict[str, TableSchema]
    ) -> None:
        col_info = self._get_column_info(table, col, schema)
        if col_info:
            col_def = self._format_column_definition(col, col_info)
            upgrade_lines.append(f"    op.add_column('{table}', {col_def})")
            downgrade_lines.append(f"    op.drop_column('{table}', '{col}')")
    
    def _process_drop_column(
        self,
        table: str,
        col: str,
        upgrade_lines: List[str],
        downgrade_lines: List[str],
        schema: Dict[str, TableSchema]
    ) -> None:
        upgrade_lines.append(f"    op.drop_column('{table}', '{col}')")
        col_info = self._get_column_info(table, col, schema)

        if col_info:
            col_def = self._format_column_definition(col, col_info)
            downgrade_lines.append(f"    op.add_column('{table}', {col_def})")
    
    def _process_alter_column(
        self,
        table: str,
        col: str,
        upgrade_lines: List[str],
        downgrade_lines: List[str],
        migration_schema: Dict[str, TableSchema],
        model_schema: Dict[str, TableSchema]
    ) -> None:
        old_info = self._get_column_info(table, col, migration_schema)
        new_info = self._get_column_info(table, col, model_schema)
        
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
    
    def _get_column_definitions(
        self,
        table_name: str, 
        schema: Dict[str, TableSchema]
    ) -> List[str]:
        if table_name not in schema:
            return []
        
        defs = []
        for col in schema[table_name].columns:
            sa_type = self.type_normalizer.get_sa_type(col.type)
            col_str = f"sa.Column('{col.name}', {sa_type}"

            if not col.nullable:
                col_str += ", nullable=False"

            if col.default:
                col_str += f", server_default='{col.default}'"

            col_str += ")"
            defs.append(col_str)

        return defs
    
    def _get_column_info(
        self,
        table_name: str,
        col_name: str, 
        schema: Dict[str, TableSchema]
    ) -> Optional[Dict]:
        if table_name not in schema:
            return None
        
        for col in schema[table_name].columns:
            if col.name == col_name:
                return {
                    "type": self.type_normalizer.get_sa_type(col.type),
                    "nullable": col.nullable,
                    "default": col.default,
                }

        return None
    
    def _format_column_definition(self, col_name: str, col_info: Dict) -> str:
        col_def = f"sa.Column('{col_name}', {col_info['type']}"

        if not col_info['nullable']:
            col_def += ", nullable=False"

        if col_info.get('default'):
            col_def += f", server_default='{col_info['default']}'"

        col_def += ")"
        return col_def
    
    def _format_operations(self, operations: List[str]) -> str:
        if not operations:
            return "    pass"
        
        return "\n".join(operations)
    
    def _render_template(
        self,
        message: str,
        rev_id: str,
        head_revision: Optional[str],
        now: str,
        upgrade_str: str,
        downgrade_str: str
    ) -> str:
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
