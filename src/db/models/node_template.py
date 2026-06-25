from typing import Optional, Dict, Any

from src.db.models.base import BaseModelConfig


class PluginModel(BaseModelConfig):
    id: str
    name: str
    description: Optional[str] = None
    version: str
    plugin_path: str
    input_model: str
    output_model: str
    parameters_schema: Optional[Dict[str, Any]] = None
    docker_image: Optional[str] = None
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class InputMappingRule(BaseModelConfig):
    target_field: str
    source: str
    transform: str = "passthrough"


class NodeTemplateModel(BaseModelConfig):
    id: str
    user_id: Optional[str] = None
    plugin_id: str
    name: str
    description: Optional[str] = None
    parameters: Dict[str, Any] = {}
    input_mapping: Optional[list] = None
    prompt_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    plugin: Optional["PluginModel"] = None
    prompt: Optional["PromptModel"] = None

from src.db.models.prompt import PromptModel
NodeTemplateModel.model_rebuild()
