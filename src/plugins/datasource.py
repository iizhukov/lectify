import json
import mimetypes
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DataSource(BaseModel):
    type: Literal["file", "prompt", "config", "text"]
    filename: Optional[str] = Field(default=None, description="Имя файла в /input/. Если не задано — name + ext.")
    required: bool = Field(default=True, description="Если True и файл не найден — ошибка запуска.")
    value: Optional[str] = Field(default=None, description="Статическое значение (для type=text).")


class SourceFile:
    """
    Файловый объект, который плагин получает через manifest.source.get(name).
    Интерфейс аналогичен стандартному файловому объекту.

    path    — абсолютный путь внутри контейнера, напр. /input/audio.m4a
    name    — имя файла, напр. audio.m4a
    format  — расширение без точки, напр. m4a
    fullname — полное имя (то же что name)
    read()  — читает содержимое
    """
    __slots__ = ("_path",)

    def __init__(self, path: str):
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return Path(self._path).name

    @property
    def format(self) -> str:
        return Path(self._path).suffix.lstrip(".")

    @property
    def fullname(self) -> str:
        return self.name

    def read(self) -> bytes:
        return Path(self._path).read_bytes()

    def read_text(self, encoding: str = "utf-8") -> str:
        return Path(self._path).read_text(encoding=encoding)

    def read_json(self) -> dict:
        return json.loads(Path(self._path).read_text(encoding="utf-8"))

    @property
    def mime_type(self) -> str:
        guess = mimetypes.guess_type(self._path)[0]
        return guess or "application/octet-stream"

    def __repr__(self) -> str:
        return f"SourceFile({self._path!r})"


class DataSourceManifest:
    """
    Объект, передаваемый в execute() плагина через context.manifest.

    sources — доступ к файловым объектам
    extra   — произвольные строковые metadata (prompt_title, mime_type, ...)
    errors  — ошибки required=False источников
    """
    __slots__ = ("_manifest",)

    def __init__(
        self,
        sources: dict[str, str] | None = None,
        errors: Optional[dict[str, str]] = None,
        extra: Optional[dict[str, str]] = None,
    ):
        self._manifest: dict = {
            "sources": dict(sources or {}),
            "errors": dict(errors or {}),
            "extra": dict(extra or {}),
        }

    @classmethod
    def from_path(cls, path: Path | str) -> Optional["DataSourceManifest"]:
        p = Path(path)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))

            return cls(
                sources=data.get("sources", {}),
                errors=data.get("errors", {}),
                extra=data.get("extra", {}),
            )
        except (json.JSONDecodeError, OSError):
            return None

    def get(self, name: str) -> Optional[SourceFile]:
        path = self._manifest["sources"].get(name)

        if path:
            return SourceFile(path)
        
        return None

    def path(self, name: str) -> Optional[str]:
        return self._manifest["sources"].get(name)

    def extra(self, name: str) -> dict[str, str]:
        prefix = f"{name}_"
        return {
            k[len(prefix):]: v
            for k, v in self._manifest["extra"].items()
            if k.startswith(prefix)
        }

    def error(self, name: str) -> Optional[str]:
        return self._manifest["errors"].get(name)

    @property
    def errors(self) -> dict[str, str]:
        return self._manifest["errors"]

    @property
    def extra_all(self) -> dict[str, str]:
        return self._manifest["extra"]

    def _to_manifest_dict(self) -> dict:
        return self._manifest


# ─── Output side ──────────────────────────────────────────────────────────────

class OutputSource(BaseModel):
    type: Literal["file", "text", "prompt", "config"]
    filename: Optional[str] = Field(default=None, description="Имя файла в /output/. Если не задано — выводизодит из output_model field.")
    content: Optional[str] = Field(default=None, description="Статический контент (для type=text).")


class OutputManifest:
    """
    Объект, через который плагин объявляет выходные артефакты.
    Передаётся в execute() через context.output.

    usage:
        with context.output.declare("result", type="file") as artifact:
            artifact.write(content)
            artifact.metadata["format"] = "md"

        сontxt.output.declare_text("summary", "some text content")
    """
    __slots__ = ("_artifacts", "_output_dir")

    def __init__(self, output_dir: Path | str = "/output"):
        self._output_dir = Path(output_dir)
        self._artifacts: dict[str, _Artifact] = {}

    def declare(self, name: str, type: Literal["file", "text", "prompt", "config"] = "file") -> "_Artifact":
        artifact = _Artifact(name=name, type=type, output_dir=self._output_dir)
        self._artifacts[name] = artifact
        return artifact

    def declare_text(self, name: str, content: str) -> "_Artifact":
        artifact = _Artifact(name=name, type="text", output_dir=self._output_dir)
        artifact.write(content)
        self._artifacts[name] = artifact
        return artifact

    def declare_file(self, name: str, source_path: Path | str) -> "_Artifact":
        import shutil
        artifact = _Artifact(name=name, type="file", output_dir=self._output_dir)
        shutil.copy2(str(source_path), artifact._path)
        self._artifacts[name] = artifact
        return artifact

    def artifacts(self) -> dict[str, "_Artifact"]:
        return self._artifacts


class _Artifact:
    __slots__ = ("name", "type", "_path", "_content", "metadata", "_closed")

    def __init__(self, name: str, type: str, output_dir: Path):
        self.name = name
        self.type = type
        self._path = output_dir / name
        self._content: Optional[bytes | str] = None
        self.metadata: dict = {}
        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    def write(self, data: str | bytes) -> None:
        if self._closed:
            raise RuntimeError("Artifact already closed")
        self._content = data

    def finalize(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._content is None:
            return
        mode = "w" if isinstance(self._content, str) else "wb"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(self._content) if isinstance(self._content, bytes) \
            else self._path.write_text(str(self._content), encoding="utf-8")

    def __enter__(self) -> "_Artifact":
        return self

    def __exit__(self, *_) -> None:
        self.finalize()
