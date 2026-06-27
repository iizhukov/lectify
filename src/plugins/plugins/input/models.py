"""
Input Plugin Models

Модели для плагина input — source node для динамической загрузки файлов в workflow.
"""

from typing import Optional
from pydantic import BaseModel


class InputPluginInput(BaseModel):
    """Input: file_id и метаданные передаются через input_mapping при запуске execution."""
    file_id: str
    # Опциональные метаданные, передаваемые оркестратором, чтобы избежать обращения к БД из контейнера
    filename: Optional[str] = None
    minio_path: Optional[str] = None
    file_path: Optional[str] = None
    size: Optional[int] = None
    content_type: Optional[str] = None


class InputPluginOutput(BaseModel):
    """Output: file_id, minio:// path, and input type."""
    file_id: str
    file_path: str  # minio:// URL
    input_type: str  # audio, video, pdf, text, image, any
