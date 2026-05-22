from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from enum import StrEnum


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowNodeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file_id: str
    node_id: str
    node_name: str
    status: str
    message: Optional[str] = None
    artifact_path: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


class WorkflowStateModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_id: str
    name: str
    status: NodeStatus
    final_artifact_path: Optional[str] = None
    created_at: datetime
    ended_at: Optional[str] = None


class FileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    language: str
    status: str
    created_at: datetime
    nodes: List[WorkflowNodeModel] = []
    workflows: List[WorkflowStateModel] = []
