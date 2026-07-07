import sys

from abc import ABC, abstractmethod
from pathlib import Path

from config.models import ServiceManifest
from templates import env


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

    def write(self, rel_path: str, content: str) -> None:
        path = self.output / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.files_written += 1

    def write_root(self, rel_path: str, content: str, skip_exist: bool = False) -> None:
        path = self.output.parent / rel_path

        if skip_exist and path.exists():
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.files_written += 1

    def render(self, template_name: str, **kwargs) -> str:
        tmpl = env.get_template(template_name)
        return tmpl.render(
            service=self.svc,
            manifest=self.manifest,
            svc_dir=self.svc_dir,
            **kwargs
        )
