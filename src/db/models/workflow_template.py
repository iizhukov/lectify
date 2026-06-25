from typing import List, Optional

from src.db.models.base import BaseModelConfig
from src.db.models.node_template import NodeTemplateModel


class WorkflowGraphNode(BaseModelConfig):
    id: str
    template_id: str
    position_x: float = 0
    position_y: float = 0


class WorkflowGraphEdge(BaseModelConfig):
    from_node: str
    to_node: str


class WorkflowGraph(BaseModelConfig):
    nodes: List[WorkflowGraphNode] = []
    edges: List[WorkflowGraphEdge] = []


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
