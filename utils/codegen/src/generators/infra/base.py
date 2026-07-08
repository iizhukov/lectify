import os

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from config.models import ServiceManifest
from templates import env
from utils import get_repo_root
from context import get_context_manager
from settings import get_settings


class BaseGenerator(ABC):
    def __init__(self, manifests: List[ServiceManifest], output: Path) -> None:
        self.manifests = manifests
        self.output = output
        self.files_written = 0

    @abstractmethod
    def generate(self) -> None:
        ...

    def write(self, rel_path: str, content: str, skip_exist: bool = False, executable: bool = False) -> None:
        self._write(
            self.output / rel_path,
            content,
            skip_exist,
            executable,
        )   

    def write_project(self, rel_path: str, content: str, skip_exist: bool = False, executable: bool = False) -> None:
        self._write(
            get_repo_root() / rel_path,
            content,
            skip_exist,
            executable,
        )

    def _write(self, path: Path, content: str, skip_exist: bool = False, executable: bool = False,) -> None:
        if skip_exist and path.exists():
            return
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        if executable:
            os.chmod(path, 0o755)

        self.files_written += 1

    def render(self, template_name: str, **kwargs) -> str:
        tmpl = env.get_template(template_name)
        context = get_context_manager()
        return tmpl.render(
            manifests=self.manifests,
            settings=get_settings(),
            context=context.get_context(),
            **kwargs
        )
