from typing import Dict, List
from .models import TableSchema


class SchemaComparator:
    @staticmethod
    def diff_schemas(
        source: Dict[str, TableSchema], 
        target: Dict[str, TableSchema]
    ) -> List[str]:
        ops = []
        
        source_tables = set(source.keys())
        target_tables = set(target.keys())
        
        for table in sorted(target_tables - source_tables):
            ops.append(f"create_table:{table}")
        
        for table in sorted(source_tables - target_tables):
            ops.append(f"drop_table:{table}")
        
        for table in sorted(source_tables & target_tables):
            source_cols = {c.name: c for c in source[table].columns}
            target_cols = {c.name: c for c in target[table].columns}
            
            for col in sorted(set(target_cols.keys()) - set(source_cols.keys())):
                ops.append(f"add_column:{table}:{col}")
            
            for col in sorted(set(source_cols.keys()) - set(target_cols.keys())):
                ops.append(f"drop_column:{table}:{col}")
            
            for col in sorted(set(source_cols.keys()) & set(target_cols.keys())):
                source_col = source_cols[col]
                target_col = target_cols[col]
                if (source_col.type != target_col.type or
                    source_col.nullable != target_col.nullable or
                    source_col.default != target_col.default):
                    ops.append(f"alter_column:{table}:{col}")
        
        return ops
    
    @staticmethod
    def generate_message(diff: List[str]) -> str:
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
