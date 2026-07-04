from dataclasses import dataclass, field
from typing import Optional, List, Any


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool = True
    default: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "nullable": self.nullable,
            "default": self.default
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ColumnInfo":
        return cls(
            name=data["name"],
            type=data["type"],
            nullable=data.get("nullable", True),
            default=data.get("default")
        )


@dataclass
class TableSchema:
    columns: List[ColumnInfo] = field(default_factory=list)
    is_dropped: bool = False
    dropped_columns: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        result = {
            "columns": [c.to_dict() for c in self.columns]
        }
        if self.is_dropped:
            result["_dropped_table"] = True
        if self.dropped_columns:
            result["_dropped_columns"] = self.dropped_columns
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> "TableSchema":
        columns = [ColumnInfo.from_dict(c) for c in data.get("columns", [])]
        return cls(
            columns=columns,
            is_dropped=data.get("_dropped_table", False),
            dropped_columns=data.get("_dropped_columns", [])
        )


@dataclass
class MigrationInfo:
    name: str
    sequence: int
    revision: str
    description: str
    applied: bool = False


@dataclass
class MigrationResult:
    applied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[dict] = field(default_factory=list)


@dataclass
class MakeMigrationResult:
    migration_file: Optional[str] = None
    revision: Optional[str] = None
    changes: List[str] = field(default_factory=list)
    error: Optional[str] = None
    message: Optional[str] = None
