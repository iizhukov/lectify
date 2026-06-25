import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db.models import NodeTemplateModel
from src.db.repository import NodeTemplateRepository
from src.plugins.registry import get_plugin_registry

router = APIRouter(prefix="/api/nodes", tags=["nodes"])
repo = NodeTemplateRepository()


class CreateNodeRequest(BaseModel):
    plugin_id: str
    name: str
    description: Optional[str] = None
    parameters: dict = {}
    input_mapping: Optional[List[dict]] = None
    prompt_id: Optional[str] = None


class UpdateNodeRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[dict] = None
    input_mapping: Optional[List[dict]] = None
    prompt_id: Optional[str] = None


@router.get("/plugins")
async def list_plugins():
    registry = get_plugin_registry()
    return registry.get_plugins_metadata()


@router.get("/plugins/{plugin_id}")
async def get_plugin(plugin_id: str):
    registry = get_plugin_registry()
    metadata = registry.get_plugin_metadata(plugin_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Plugin not found")
    plugin_class = registry.get_plugin(plugin_id)
    if plugin_class:
        schema = plugin_class().get_schema()
        metadata = dict(metadata)
        metadata["schema"] = schema.model_dump()
    return metadata


# ---- Node template CRUD ----

@router.get("", response_model=List[NodeTemplateModel])
async def list_nodes(user_id: Optional[str] = None):
    if user_id:
        user_nodes = repo.get_by_user(user_id)
        global_nodes = repo.get_global()
        return global_nodes + user_nodes
    return repo.get_global()


@router.post("", response_model=NodeTemplateModel)
async def create_node(request: CreateNodeRequest, user_id: Optional[str] = None):
    registry = get_plugin_registry()
    if not registry.get_plugin(request.plugin_id):
        raise HTTPException(status_code=400, detail=f"Plugin not found: {request.plugin_id}")
    return repo.create({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "plugin_id": request.plugin_id,
        "name": request.name,
        "description": request.description,
        "parameters": request.parameters,
        "input_mapping": request.input_mapping,
        "prompt_id": request.prompt_id,
    })


@router.get("/{node_id}", response_model=NodeTemplateModel)
async def get_node(node_id: str):
    node = repo.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.put("/{node_id}", response_model=NodeTemplateModel)
async def update_node(node_id: str, request: UpdateNodeRequest):
    update_data = {k: v for k, v in request.model_dump().items() if v is not None}
    node = repo.update(node_id, **update_data)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.delete("/{node_id}")
async def delete_node(node_id: str):
    node = repo.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.user_id is None:
        raise HTTPException(status_code=400, detail="Cannot delete global node templates")
    repo.delete(node_id)
    return {"ok": True}
