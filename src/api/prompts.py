import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db.models import PromptModel
from src.db.repository import PromptRepository

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class CreatePromptRequest(BaseModel):
    name: str
    system_prompt: Optional[str] = None
    user_prompt_template: str
    variables: Optional[List[str]] = None


class UpdatePromptRequest(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    variables: Optional[List[str]] = None


@router.get("", response_model=List[PromptModel])
async def list_prompts(user_id: Optional[str] = None):
    """
    List all prompts (global + user's).
    Returns prompts filtered by user_id if provided.
    """
    repo = PromptRepository()

    if user_id:
        global_prompts = repo.get_global()
        user_prompts = repo.get_by_user(user_id)
        prompts = global_prompts + user_prompts
    else:
        prompts = repo.get_global()

    return [PromptModel.model_validate(p) for p in prompts]


@router.get("/{prompt_id}", response_model=PromptModel)
async def get_prompt(prompt_id: str):
    """Get prompt by ID"""
    repo = PromptRepository()
    prompt = repo.get(prompt_id)

    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    return PromptModel.model_validate(prompt)


@router.post("", response_model=PromptModel)
async def create_prompt(
    request: CreatePromptRequest,
    user_id: Optional[str] = None
):
    """Create a new prompt"""
    repo = PromptRepository()

    prompt = repo.create({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "name": request.name,
        "system_prompt": request.system_prompt,
        "user_prompt_template": request.user_prompt_template,
        "variables": request.variables or [],
    })

    return PromptModel.model_validate(prompt)


@router.put("/{prompt_id}", response_model=PromptModel)
async def update_prompt(
    prompt_id: str,
    request: UpdatePromptRequest
):
    """Update a prompt"""
    repo = PromptRepository()

    update_data = {}
    if request.name is not None:
        update_data["name"] = request.name
    if request.system_prompt is not None:
        update_data["system_prompt"] = request.system_prompt
    if request.user_prompt_template is not None:
        update_data["user_prompt_template"] = request.user_prompt_template
    if request.variables is not None:
        update_data["variables"] = request.variables

    prompt = repo.update(prompt_id, **update_data)

    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    return PromptModel.model_validate(prompt)


@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: str):
    """Delete a prompt"""
    repo = PromptRepository()
    success = repo.delete(prompt_id)

    if not success:
        raise HTTPException(status_code=404, detail="Prompt not found")

    return {"status": "ok"}


@router.get("/{prompt_id}/render")
async def render_prompt(
    prompt_id: str,
    name: Optional[str] = None,
    value: Optional[str] = None
):
    """Render prompt with variables substituted"""
    repo = PromptRepository()
    prompt = repo.get(prompt_id)

    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    system = prompt.system_prompt or ""
    user_template = prompt.user_prompt_template or ""

    variables = {}
    if name is not None and value is not None:
        variables[name] = value

    for var_name, var_value in variables.items():
        placeholder = f"{{{{{var_name}}}}}"
        system = system.replace(placeholder, str(var_value))
        user_template = user_template.replace(placeholder, str(var_value))

    return {
        "system_prompt": system,
        "user_prompt": user_template
    }
