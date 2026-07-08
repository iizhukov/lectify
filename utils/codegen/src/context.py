import json
import secrets
import string

from typing import Optional, Dict
from datetime import datetime

from pydantic import BaseModel, Field

from utils import get_repo_root


class ServiceContext(BaseModel):
    minio_password: Optional[str] = None
    postgres_password: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ContextData(BaseModel):
    services: Dict[str, ServiceContext] = Field(default_factory=dict)


class ContextManager:
    def __init__(self):
        self.root_path = get_repo_root()
        self.context_file = self.root_path / ".codegen" / "context.json"
        self.context_file.parent.mkdir(parents=True, exist_ok=True)

        self._data = self._load()
    
    def _load(self) -> ContextData:
        if self.context_file.exists():
            try:
                with open(self.context_file) as f:
                    data = json.load(f)
                    return ContextData(**data)
            except Exception as e:
                print(f"⚠️ Failed to load context: {e}")
                return ContextData()
        else:
            return ContextData()
    
    def _save(self):
        with open(self.context_file, "w") as f:
            json.dump(self._data.model_dump(), f, indent=2, ensure_ascii=False)

    def get_context(self) -> ContextData:
        return self._data
    
    def get_service_context(self, service_name: str) -> ServiceContext:
        if service_name not in self._data.services:
            self._data.services[service_name] = ServiceContext()
            self._save()

        return self._data.services[service_name]
    
    def generate_password(self, length: int = 16) -> str:
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def ensure_minio_password(self, service_name: str) -> str:
        context = self.get_service_context(service_name)

        if not context.minio_password:
            context.minio_password = self.generate_password()
            context.updated_at = datetime.now().isoformat()
            self._save()

        return context.minio_password
    
    def ensure_postgres_password(self, service_name: str) -> str:
        context = self.get_service_context(service_name)

        if not context.postgres_password:
            context.postgres_password = self.generate_password()
            context.updated_at = datetime.now().isoformat()
            self._save()

        return context.postgres_password
    
    def delete_service(self, service_name: str):
        if service_name in self._data.services:
            del self._data.services[service_name]
            self._save()
    
    def list_services(self) -> list[str]:
        return list(self._data.services.keys())


_context_manager: Optional[ContextManager] = None


def get_context_manager() -> ContextManager:
    global _context_manager

    if _context_manager is None:
        _context_manager = ContextManager()

    return _context_manager
