"""
Database models and repository

Import SQLAlchemy models:
    from src.db.database import Base, engine, SessionLocal

Import Pydantic models:
    from src.db.models import (
        NodeStatus, FileStatus,
        FileModel, WorkflowStateModel, WorkflowNodeModel,
        WorkflowGraphModel, WorkflowEdgeModel, ArtifactModel,
        # v2 models
        ExecutionStatus, NodeExecutionStatus,
        UserModel, PluginModel, NodeTemplateModel, InputMappingRule,
        PromptModel, WorkflowGraphNode, WorkflowGraphEdge, WorkflowGraph,
        WorkflowTemplateModel, PublicWorkflowModel, ExecutionModel, ExecutionNodeModel,
    )

Import SQLAlchemy entities (v2):
    from src.db.entities import (
        DBUser, DBPlugin, DBNodeTemplate, DBWorkflowTemplate,
        DBWorkflowPublic, DBPrompt, DBExecution, DBExecutionNode,
        ExecutionStatus as DBExecutionStatus,
        NodeExecutionStatus as DBNodeExecutionStatus,
    )

Import repository:
    from src.db.repository import DBRepository
"""

# Note: We don't import database.py here because it triggers database connection
# Users should import from specific modules as shown in the docstring above

# Re-export pydantic models for convenience
from src.db.models import (
    # Enums
    NodeStatus, FileStatus,
    # v1 File models
    FileModel, WorkflowStateModel, WorkflowNodeModel,
    WorkflowGraphModel, WorkflowEdgeModel, ArtifactModel,
    # v2 Enums
    ExecutionStatus, NodeExecutionStatus,
    # v2 Pydantic models
    UserModel, PluginModel, NodeTemplateModel, InputMappingRule,
    PromptModel, WorkflowGraphNode, WorkflowGraphEdge, WorkflowGraph,
    WorkflowTemplateModel, PublicWorkflowModel, ExecutionModel, ExecutionNodeModel,
)

# Note: DBRepository must be imported directly due to circular imports
# from src.db.repository import DBRepository

__all__ = [
    # v1 Enums
    "NodeStatus", "FileStatus",
    # v1 Pydantic models
    "FileModel", "WorkflowStateModel", "WorkflowNodeModel",
    "WorkflowGraphModel", "WorkflowEdgeModel", "ArtifactModel",
    # v2 Enums
    "ExecutionStatus", "NodeExecutionStatus",
    # v2 Pydantic models
    "UserModel", "PluginModel", "NodeTemplateModel", "InputMappingRule",
    "PromptModel", "WorkflowGraphNode", "WorkflowGraphEdge", "WorkflowGraph",
    "WorkflowTemplateModel", "PublicWorkflowModel", "ExecutionModel", "ExecutionNodeModel",
]