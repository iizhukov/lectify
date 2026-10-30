import sys
from abc import ABC, abstractmethod
from pathlib import Path

from config.plugin_models import PluginManifest
from templates import env
from utils import get_repo_root


class BasePluginGenerator(ABC):
    def __init__(self, manifest: PluginManifest, output: Path, docker: bool = False) -> None:
        self.manifest = manifest
        self.plugin = manifest.plugin
        self.output = output
        self.plugin_dir = output.parent
        self.files_written = 0
        self.docker = docker

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

    def _write(self, path: Path, content: str, skip_exist: bool = False, executable: bool = False) -> None:
        if skip_exist and path.exists():
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        if executable:
            import os
            os.chmod(path, 0o755)

        self.files_written += 1

    def render(self, template_name: str, **kwargs) -> str:
        tmpl = env.get_template(template_name)
        return tmpl.render(
            plugin=self.plugin,
            manifest=self.manifest,
            plugin_dir=self.plugin_dir,
            **kwargs,
        )
