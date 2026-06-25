"""
Nodes API — CRUD for node templates
"""

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


# =============================================
# NODE TEMPLATES CRUD
# =============================================

@router.get("", response_model=List[NodeTemplateModel])
async def list_nodes(user_id: Optional[str] = None):
    """
    List all node templates (global + user's).

    MIGRATED: use NodeTemplateRepository.get_by_user() / get_global()
    DEPRECATED: old repo.get_user_node_templates() / get_global_node_templates()
    """
    raise NotImplementedError(
        "MIGRATED: use NodeTemplateRepository.get_by_user() / get_global()"
    )

    # OLD:
    # if user_id:
    #     user_nodes = repo.get_user_node_templates(user_id)
    #     global_nodes = repo.get_global_node_templates()
    #     nodes = global_nodes + user_nodes
    # else:
    #     nodes = repo.get_global_node_templates()
    # return [
    #     NodeTemplateModel(
    #         id=n.id, user_id=n.user_id, plugin_id=n.plugin_id,
    #         name=n.name, description=n.description,
    #         parameters=n.parameters, input_mapping=n.input_mapping,
    #         prompt_id=n.prompt_id, created_at=n.created_at,
    #         updated_at=n.updated_at
    #     )
    #     for n in nodes
    # ]


@router.get("/plugins")
async def list_plugins():
    """
    List all available plugins.

    MIGRATED: unchanged — uses PluginRepository via get_plugin_registry()
    """
    registry = get_plugin_registry()
    return registry.get_plugins_metadata()


@router.get("/plugins/{plugin_id}")
async def get_plugin(plugin_id: str):
    """
    Get plugin details.

    MIGRATED: unchanged — uses get_plugin_registry()
    """
    registry = get_plugin_registry()
    metadata = registry.get_plugin_metadata(plugin_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Plugin not found")

    plugin_class = registry.get_plugin(plugin_id)
    if plugin_class:
        schema = plugin_class().get_schema()
        metadata["schema"] = schema.model_dump()

    return metadata


@router.get("/{node_id}", response_model=NodeTemplateModel)
async def get_node(node_id: str):
    """
    Get node template by ID.

    MIGRATED: use NodeTemplateRepository.get(node_id)
    """
    raise NotImplementedError(
        "MIGRATED: use NodeTemplateRepository.get(node_id)"
    )

    # OLD:
    # node = repo.get_node_template(node_id)
    # if not node:
    #     raise HTTPException(status_code=404, detail="Node not found")
    # return NodeTemplateModel(
    #     id=node.id, user_id=node.user_id, plugin_id=node.plugin_id,
    #     name=node.name, description=node.description,
    #     parameters=node.parameters, input_mapping=node.input_mapping,
    #     prompt_id=node.prompt_id, created_at=node.created_at,
    #     updated_at=node.updated_at
    # )


@router.post("", response_model=NodeTemplateModel)
async def create_node(request: CreateNodeRequest, user_id: Optional[str] = None):
    """
    Create a new node template.

    MIGRATED: use NodeTemplateRepository.create(data)
    """
    raise NotImplementedError(
        "MIGRATED: use NodeTemplateRepository.create(data)"
    )

    # OLD:
    # registry = get_plugin_registry()
    # if not registry.get_plugin(request.plugin_id):
    #     raise HTTPException(status_code=400, detail=f"Plugin not found: {request.plugin_id}")
    # node = repo.create_node_template({
    #     "id": str(uuid.uuid4()), "user_id": user_id,
    #     "plugin_id": request.plugin_id, "name": request.name,
    #     "description": request.description,
    #     "parameters": request.parameters,
    #     "input_mapping": request.input_mapping,
    #     "prompt_id": request.prompt_id
    # })
    # return NodeTemplateModel(
    #     id=node.id, user_id=node.user_id, plugin_id=node.plugin_id,
    #     name=node.name, description=node.description,
    #     parameters=node.parameters, input_mapping=node.input_mapping,
    #     prompt_id=node.prompt_id, created_at=node.created_at,
    #     updated_at=node.updated_at
    # )


@router.put("/{node_id}", response_model=NodeTemplateModel)
async def update_node(node_id: str, request: UpdateNodeRequest):
    """
    Update a node template.

    MIGRATED: use NodeTemplateRepository.update(node_id, **data)
    """
    raise NotImplementedError(
        "MIGRATED: use NodeTemplateRepository.update(node_id, **data)"
    )

    # OLD:
    # update_data = {}
    # if request.name is not None:
    #     update_data["name"] = request.name
    # if request.description is not None:
    #     update_data["description"] = request.description
    # if request.parameters is not None:
    #     update_data["parameters"] = request.parameters
    # if request.input_mapping is not None:
    #     update_data["input_mapping"] = request.input_mapping
    # if request.prompt_id is not None:
    #     update_data["prompt_id"] = request.prompt_id
    # node = repo.update_node_template(node_id, **update_data)
    # if not node:
    #     raise HTTPException(status_code=404, detail="Node not found")
    # return NodeTemplateModel(
    #     id=node.id, user_id=node.user_id, plugin_id=node.plugin_id,
    #     name=node.name, description=node.description,
    #     parameters=node.parameters, input_mapping=node.input_mapping,
    #     prompt_id=node.prompt_id, created_at=node.created_at,
    #     updated_at=node.updated_at
    # )


@router.delete("/{node_id}")
async def delete_node(node_id: str):
    """
    Delete a node template.

    MIGRATED: use NodeTemplateRepository.delete(node_id)
    """
    raise NotImplementedError(
        "MIGRATED: use NodeTemplateRepository.delete(node_id)"
    )

    # OLD:
    # node = repo.get_node_template(node_id)
    # if not node:
    #     raise HTTPException(status_code=404, detail="Node not found")
    # if node.user_id is None:
    #     raise HTTPException(status_code=400, detail="Cannot delete global node templates")
    # from src.db.database import engine
    # from sqlalchemy.orm import Session
    # with Session(engine) as session:
    #     db_node = session.query(type(node)).filter_by(id=node_id).first()
    #     if db_node:
    #         session.delete(db_node)
    #         session.commit()
    # return {"status": "ok"}
