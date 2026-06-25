"""
Plugin input/output models for media_converter
"""

from pydantic import BaseModel


class MediaConverterInput(BaseModel):
    """Input for media converter plugin"""
    file_id: str
    file_path: str


class MediaConverterOutput(BaseModel):
    """Output from media converter plugin"""
    file_id: str
    media_path: str
    format: str = "m4a"
    duration_ms: int = 0