from enum import Enum
from typing import Optional, List

from src.db.models.base import BaseModelConfig
from src.db.models.node_template import NodeTemplateModel
from src.db.models.workflow_template import WorkflowTemplateModel


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionNodeModel(BaseModelConfig):
    id: str
    execution_id: str
    node_template_id: Optional[str] = None
    node_id: str
    plugin_id: Optional[str] = None
    node_name: str = ""
    status: NodeExecutionStatus
    progress_percent: Optional[int] = None
    progress_message: Optional[str] = None
    input_data: Optional[dict] = None
    output_data: Optional[dict] = None
    container_id: Optional[str] = None
    cpu_percent: Optional[float] = None
    avg_cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    execution_time_ms: Optional[int] = None
    duration_str: Optional[str] = None
    error_message: Optional[str] = None
    logs_path: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    created_at: Optional[str] = None

    node_template: Optional[NodeTemplateModel] = None
    artifacts: Optional[list] = None


class ExecutionModel(BaseModelConfig):
    id: str
    workflow_id: Optional[str] = None  # DEPRECATED: use workflow_template_id
    workflow_template_id: Optional[str] = None
    file_id: Optional[str] = None  # deprecated, для single-file workflows
    user_id: Optional[str] = None
    workflow_name: Optional[str] = None  # from mock: execution-level name
    file_name: Optional[str] = None  # from mock: file name for the execution
    language: str = "ru"  # from mock: language for the execution
    input_files: Optional[dict] = {}  # {node_id: file_id} для множественных входов
    status: ExecutionStatus
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None

    nodes: Optional[List[ExecutionNodeModel]] = None
    workflow_template: Optional[WorkflowTemplateModel] = None
