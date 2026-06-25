from typing import List, Optional, Any

from src.db.models.base import BaseModelConfig


# ---- MIGRATED: flat graph models matching frontend mock contract ----
# Mock contract (mock/mock_data.py):
#   nodes: [{"id", "plugin_id", "name", "description", "parameters",
#             "input_mapping": [...], "prompt_id"}]
#   edges: [{"from_node_id", "to_node_id"}]

class WorkflowGraphNode(BaseModelConfig):
    """Node definition inside a workflow graph. Mirrors frontend mock contract."""
    id: str
    plugin_id: str
    name: str
    description: str = ""
    parameters: dict[str, Any] = {}
    input_mapping: list[dict[str, Any]] = []
    prompt_id: Optional[str] = None


class WorkflowGraphEdge(BaseModelConfig):
    """Edge between nodes in a workflow graph. Mirrors frontend mock contract."""
    from_node_id: str
    to_node_id: str


class WorkflowGraph(BaseModelConfig):
    """Workflow graph — list of nodes and edges. Mirrors frontend mock contract."""
    nodes: List[WorkflowGraphNode] = []
    edges: List[WorkflowGraphEdge] = []


# ---- LEGACY: position-based models (deprecated, use the flat models above) ----
# DEPRECATED: use WorkflowGraphNode / WorkflowGraphEdge instead
class _LegacyWorkflowGraphNode(BaseModelConfig):
    id: str
    template_id: str
    position_x: float = 0
    position_y: float = 0


class _LegacyWorkflowGraphEdge(BaseModelConfig):
    from_node: str
    to_node: str


class _LegacyWorkflowGraph(BaseModelConfig):
    nodes: List[_LegacyWorkflowGraphNode] = []
    edges: List[_LegacyWorkflowGraphEdge] = []


class WorkflowTemplateModel(BaseModelConfig):
    id: str
    user_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    graph: WorkflowGraph
    is_public: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    node_templates: Optional[List["NodeTemplateModel"]] = None


from src.db.models.node_template import NodeTemplateModel
WorkflowTemplateModel.model_rebuild()


class PublicWorkflowModel(BaseModelConfig):
    id: str
    original_workflow_id: str
    name: str
    description: Optional[str] = None
    graph: WorkflowGraph
    author_id: Optional[str] = None
    usage_count: int = 0
    created_at: Optional[str] = None
