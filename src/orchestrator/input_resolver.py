import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.plugins.datasource import DataSource, DataSourceManifest
from src.utils.storage import MinIOStorage, get_storage
from src.db.database import SessionLocal
from src.db.entity import DBPrompt
from src.db.entity.file import DBFile

if TYPE_CHECKING:
    from src.plugins.base import Plugin

logger = logging.getLogger(__name__)


class InputResolver:
    """
    Resolves plugin data_sources from pre-mapped input_data (produced by _map_inputs).

    input_data already has upstream node outputs routed to the correct field names
    via the graph's input_mapping. This class reads those pre-resolved values,
    fetches files/prompts from storage, and writes them to /input/.

    For example, if input_mapping has rule:
        {target_field: "prompt_id", source: "$prompt_selector.output.prompt_id"}

    Then input_data["prompt_id"] = "prompt-uuid-string" before resolve() is called.

    The DataSource.source field tells us which key in input_data holds the value:
        data_source name "txt_file" → source="file_id" → read input_data["file_id"]
    """

    def __init__(self, storage: MinIOStorage | None = None):
        self.storage = storage or get_storage()

    def resolve(
        self,
        plugin: "Plugin",
        input_data: dict[str, Any],
        temp_dir: Path,
        parameters: dict[str, Any] | None = None,
    ) -> tuple[DataSourceManifest, dict[str, Any]]:
        data_sources = getattr(plugin, "data_sources", {})
        if not isinstance(data_sources, dict) or not data_sources:
            return DataSourceManifest(), {}

        manifest_sources: dict[str, str] = {}
        manifest_errors: dict[str, str] = {}
        extra_input: dict[str, Any] = {}

        for name, source in data_sources.items():
            if not isinstance(source, DataSource):
                logger.warning(
                    "Plugin '%s' data_source '%s' is not a DataSource instance",
                    plugin.id,
                    name,
                )
                continue

            resolved = self._resolve_one(source, name, input_data, temp_dir, parameters)
            if resolved["path"]:
                manifest_sources[name] = resolved["path"]
                extra_input[f"{name}_path"] = resolved["path"]

                if resolved.get("extra"):
                    extra_input.update(resolved["extra"])

            elif not source.required:
                manifest_errors[name] = resolved.get("error", "not found")
            else:
                raise FileNotFoundError(
                    f"Required data source '{name}' ({source.type}) not resolved "
                    f"for plugin {plugin.id}: {resolved.get('error')}"
                )

        manifest = DataSourceManifest(
            sources=manifest_sources, errors=manifest_errors, extra=extra_input
        )
        return manifest, extra_input

    def _resolve_one(
        self,
        source: DataSource,
        name: str,
        input_data: dict[str, Any],
        temp_dir: Path,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            if source.type == "file":
                return self._resolve_file(source, name, input_data, temp_dir)
            elif source.type == "prompt":
                return self._resolve_prompt(source, name, input_data, temp_dir, parameters)
            elif source.type == "text":
                return self._resolve_text(source, name, input_data, temp_dir)
            else:
                return {"path": None, "error": f"unknown type: {source.type}"}
        except Exception as e:
            logger.error(
                "Failed to resolve data source '%s' (type=%s): %s",
                name,
                source.type,
                e,
            )
            return {"path": None, "error": str(e)}

    def _resolve_file(
        self,
        source: DataSource,
        name: str,
        input_data: dict[str, Any],
        temp_dir: Path,
    ) -> dict[str, Any]:
        key = source.source or name
        value = input_data.get(key)
        if not value or not isinstance(value, (str, Path)):
            return {"path": None, "error": f"input_data has no value for '{key}'"}

        value = str(value)

        if not value.startswith("minio://"):
            session = SessionLocal()
            try:
                db_file = session.query(DBFile).filter(DBFile.id == value).first()
            finally:
                session.close()

            if db_file:
                minio_path = str(db_file.minio_path)
                db_filename = str(db_file.filename)
                ext = Path(minio_path).suffix or (db_filename and Path(db_filename).suffix) or ""
                filename = source.filename or f"{name}{ext}"
                local_path = temp_dir / "input" / filename
                local_path.parent.mkdir(parents=True, exist_ok=True)

                logger.info(
                    "Downloading file for data source '%s' by file_id: %s -> %s",
                    name,
                    minio_path,
                    local_path,
                )

                bytes_data = self.storage.get_file_bytes(minio_path)
                if bytes_data is None:
                    return {"path": None, "error": f"file not found in MinIO: {minio_path}"}

                mime = str(db_file.mime_type) if db_file else ""
                is_text = (
                    ext.lower() in [".txt", ".md", ".tex", ".json", ".yaml", ".yml"]
                    or mime.startswith("text/")
                )
                mode = "w" if is_text else "wb"
                content = bytes_data.decode("utf-8") if is_text else bytes_data
                with open(local_path, mode) as f:
                    f.write(content)

                container_path = f"/input/{filename}"
                return {
                    "path": container_path,
                    "extra": {
                        f"{key}_minio_url": f"minio://{minio_path}",
                        f"{key}_filename": filename,
                        f"{key}_mime_type": mime,
                    },
                }

            return {"path": value, "extra": {f"{key}_minio_url": value}}

        object_name = value.replace("minio://", "")
        ext = Path(object_name).suffix

        filename = source.filename or f"{key}{ext}"
        local_path = temp_dir / "input" / filename

        logger.info(
            "Downloading file for data source '%s': %s -> %s",
            key,
            object_name,
            local_path,
        )

        bytes_data = self.storage.get_file_bytes(object_name)
        if bytes_data is None:
            return {"path": None, "error": f"file not found in MinIO: {object_name}"}

        mode = "w" if ext.lower() in [".txt", ".md", ".tex", ".json", ".yaml", ".yml"] else "wb"
        if ext.lower() in [".txt", ".md", ".tex", ".json", ".yaml", ".yml"]:
            content = bytes_data.decode("utf-8")
        else:
            content = bytes_data
        with open(local_path, mode) as f:
            f.write(content)

        container_path = f"/input/{filename}"
        return {
            "path": container_path,
            "extra": {
                f"{key}_minio_url": value,
                f"{key}_filename": filename,
            },
        }

    def _resolve_prompt(
        self,
        source: DataSource,
        name: str,
        input_data: dict[str, Any],
        temp_dir: Path,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = source.source or name
        prompt_id: str | None = None

        if parameters and "prompt_id" in parameters:
            prompt_id = parameters.get("prompt_id")
        elif key in input_data and input_data[key]:
            prompt_id = input_data[key]
        else:
            return {
                "path": None,
                "error": f"prompt source '{name}' requires 'prompt_id' in parameters or input_data",
            }

        if not prompt_id or not isinstance(prompt_id, str):
            return {
                "path": None,
                "error": f"prompt_id is not a valid string: {prompt_id!r}",
            }

        session = SessionLocal()
        try:
            prompt = session.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()
            if not prompt:
                return {"path": None, "error": f"prompt not found: {prompt_id}"}

            filename = source.filename or f"{name}.txt"
            local_path = temp_dir / "input" / filename
            content = (
                getattr(prompt, "system_prompt", "") or
                getattr(prompt, "user_prompt_template", "") or
                ""
            )
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(content)

            container_path = f"/input/{filename}"
            return {
                "path": container_path,
                "extra": {
                    f"{name}_prompt_id": prompt_id,
                    f"{name}_prompt_title": getattr(prompt, "name", ""),
                    f"{name}_system_prompt": getattr(prompt, "system_prompt", "") or "",
                    f"{name}_user_prompt_template": getattr(prompt, "user_prompt_template", "") or "",
                },
            }
        finally:
            session.close()

    def _resolve_text(
        self,
        source: DataSource,
        name: str,
        input_data: dict[str, Any],
        temp_dir: Path,
    ) -> dict[str, Any]:
        value = source.value
        if value is None:
            value = input_data.get(name)
        if value is None:
            return {"path": None, "error": f"text source '{name}' has no value (source.value is None and not in input_data)"}

        extra = {}

        if isinstance(value, str) and len(value) == 36 and value.count("-") == 4:
            session = SessionLocal()
            try:
                db_file = session.query(DBFile).filter(DBFile.id == value).first()
                if db_file and db_file.mime_type:
                    extra[f"{name}_mime_type"] = str(db_file.mime_type)
            finally:
                session.close()

        filename = source.filename or f"{name}.txt"
        local_path = temp_dir / "input" / filename
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(value)

        container_path = f"/input/{filename}"
        return {"path": container_path, "extra": extra}
