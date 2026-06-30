from datetime import datetime
from typing import List, Optional

from src.db.models.base import BaseModelConfig
from src.db.models.status import FileStatus


class ArtifactModel(BaseModelConfig):
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


class WorkflowEdgeModel(BaseModelConfig):
    from_node_id: str
    to_node_id: str


class WorkflowNodeModel(BaseModelConfig):
    id: str
    workflow_id: str
    file_id: str
    node_id: str
    node_name: str
    status: str

    message: Optional[str] = None
    artifact_path: Optional[str] = None

    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    artifacts: List[ArtifactModel] = []
    dependencies: List[str] = []


class WorkflowGraphModel(BaseModelConfig):
    nodes: List[WorkflowNodeModel]
    edges: List[WorkflowEdgeModel]


class WorkflowStateModel(BaseModelConfig):
    id: str
    file_id: str
    name: str
    status: str

    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    final_artifact_id: Optional[str] = None
    graph: Optional[WorkflowGraphModel] = None


class FileModel(BaseModelConfig):
    id: str
    filename: str
    original_path: str
    language: str
    status: FileStatus
    size_bytes: int
    mime_type: str
    minio_path: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    workflows: List[WorkflowStateModel] = []
