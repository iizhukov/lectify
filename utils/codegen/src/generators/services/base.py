import sys
import os

from abc import ABC, abstractmethod
from pathlib import Path

from config.models import ServiceManifest
from templates import env
from utils import get_repo_root
from context import get_context_manager
from settings import get_settings


class BaseGenerator(ABC):
    def __init__(self, manifest: ServiceManifest, output: Path) -> None:
        self.manifest = manifest
        self.svc = manifest.service
        self.output = output
        self.svc_dir = output.parent
        self.files_written = 0

        self._add_to_path()

    def _add_to_path(self) -> None:
        output_parent = self.output.parent

        if str(output_parent) not in sys.path:
            sys.path.insert(0, str(output_parent))

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

    def write_root(self, rel_path: str, content: str, skip_exist: bool = False, executable: bool = False) -> None:
        self._write(
            self.output.parent / rel_path,
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
        context_manager = get_context_manager()
        tmpl = env.get_template(template_name)
        return tmpl.render(
            service=self.svc,
            manifest=self.manifest,
            svc_dir=self.svc_dir,
            settings=get_settings(),
            context=context_manager.get_service_context(self.svc.name),
            **kwargs
        )
