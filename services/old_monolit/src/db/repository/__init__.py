from src.db.repository.base import BaseRepository
from src.db.repository.user import UserRepository
from src.db.repository.auth import AuthRepository
from src.db.repository.plugin import PluginRepository
from src.db.repository.node_template import NodeTemplateRepository
from src.db.repository.prompt import PromptRepository
from src.db.repository.workflow_template import WorkflowTemplateRepository
from src.db.repository.workflow import WorkflowRepository
from src.db.repository.execution import ExecutionRepository, ExecutionNodeRepository


class DBRepository(
    UserRepository,
    AuthRepository,
    PluginRepository,
    NodeTemplateRepository,
    PromptRepository,
    WorkflowTemplateRepository,
    WorkflowRepository,
    ExecutionRepository,
    ExecutionNodeRepository,
):
    """Unified repository interface combining all domain repositories via inheritance."""

    def __init__(self):
        UserRepository.__init__(self)
        AuthRepository.__init__(self)
        PluginRepository.__init__(self)
        NodeTemplateRepository.__init__(self)
        PromptRepository.__init__(self)
        WorkflowTemplateRepository.__init__(self)
        WorkflowRepository.__init__(self)
        ExecutionRepository.__init__(self)
        ExecutionNodeRepository.__init__(self)


class Repository(DBRepository):
    """Alias for backward compatibility."""
    pass


__all__ = [
    "BaseRepository",
    "UserRepository",
    "AuthRepository",
    "PluginRepository",
    "NodeTemplateRepository",
    "PromptRepository",
    "WorkflowTemplateRepository",
    "WorkflowRepository",
    "ExecutionRepository",
    "ExecutionNodeRepository",
    "DBRepository",
    "Repository",
]
