from datetime import datetime
from enum import StrEnum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FileStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_id: str
    workflow_id: str
    node_id: str

    name: str
    ext: str
    mime_type: str
    path: str
    minio_path: Optional[str] = None
    size_bytes: int

    created_at: datetime


class WorkflowEdgeModel(BaseModel):
    from_node_id: str
    to_node_id: str


class WorkflowNodeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str

    workflow_id: str
    file_id: str

    node_id: str
    node_name: str

    status: NodeStatus

    message: Optional[str] = None
    artifact_path: Optional[str] = None

    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    artifacts: List[ArtifactModel] = Field(default_factory=list)

    dependencies: List[str] = Field(default_factory=list)


class WorkflowGraphModel(BaseModel):
    nodes: List[WorkflowNodeModel]
    edges: List[WorkflowEdgeModel]


class WorkflowStateModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_id: str

    name: str
    status: NodeStatus

    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    final_artifact_id: Optional[str] = None

    graph: Optional[WorkflowGraphModel] = None


class FileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str

    filename: str
    original_path: str

    language: str

    status: FileStatus

    size_bytes: int
    mime_type: str

    created_at: datetime
    updated_at: datetime

    workflows: List[WorkflowStateModel] = Field(default_factory=list)
