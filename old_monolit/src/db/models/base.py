from pydantic import BaseModel, ConfigDict


class BaseModelConfig(BaseModel):
    """Base Pydantic model with shared config"""
    model_config = ConfigDict(from_attributes=True)
