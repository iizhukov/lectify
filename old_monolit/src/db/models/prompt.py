from typing import Optional, List

from src.db.models.base import BaseModelConfig


class PromptModel(BaseModelConfig):
    id: str
    user_id: Optional[str] = None
    name: str
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    variables: Optional[List[str]] = None
    minio_path: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
