import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.plugins.datasource import DataSource, DataSourceManifest
from src.utils.storage import MinIOStorage, get_storage
from src.db.database import SessionLocal
from src.db.entity import DBPrompt

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
        """
        Resolve all data_sources for a plugin.

        Args:
            plugin: Plugin instance with data_sources attribute
            input_data: Already-mapped input dict from _map_inputs().
                        Keys match data_source names: {"prompt_id": "...", "audio_file": "..."}
            temp_dir: Temp directory for /input/ files
            parameters: Node parameters dict (for prompt_selector's own prompt_id)

        Returns:
            (DataSourceManifest, extra_input) — manifest to write to .manifest.json,
            plus extra metadata (prompt metadata, minio URLs, etc.)
        """
        data_sources = getattr(plugin, "data_sources", {})
        if not data_sources:
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
                return self._resolve_text(source, name, temp_dir)
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
        """
        Resolve a file data source.

        input_data[name] contains the pre-mapped value from the upstream node output,
        after _map_inputs() has resolved the input_mapping. The value is typically
        a minio:// URL or a local path.
        """
        value = input_data.get(name)
        if not value or not isinstance(value, (str, Path)):
            return {"path": None, "error": f"input_data has no value for '{name}'"}

        value = str(value)

        if not value.startswith("minio://"):
            return {"path": value, "extra": {f"{name}_minio_url": value}}

        object_name = value.replace("minio://", "")
        ext = Path(object_name).suffix

        filename = source.filename or f"{name}{ext}"
        local_path = temp_dir / "input" / filename

        logger.info(
            "Downloading file for data source '%s': %s -> %s",
            name,
            object_name,
            local_path,
        )

        bytes_data = self.storage.get_file_bytes(object_name)
        if bytes_data is None:
            return {"path": None, "error": f"file not found in MinIO: {object_name}"}

        mode = "w" if ext.lower() in [".txt", ".md", ".tex", ".json", ".yaml", ".yml"] else "wb"
        with open(local_path, mode) as f:
            f.write(bytes_data)

        container_path = f"/input/{filename}"
        return {
            "path": container_path,
            "extra": {
                f"{name}_minio_url": value,
                f"{name}_filename": filename,
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
        """
        Resolve a prompt data source.

        For prompt_selector: reads from parameters["prompt_id"] directly.
        For downstream plugins (llm_request, text_to_md, etc.):
        input_data[name] contains the prompt_id string, after input_mapping
        routed $prompt_selector.output.prompt_id → input_data["prompt_id"].
        """
        prompt_id: str | None = None

        if parameters and "prompt_id" in parameters:
            prompt_id = parameters.get("prompt_id")
        elif name in input_data and input_data[name]:
            prompt_id = input_data[name]
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
        temp_dir: Path,
    ) -> dict[str, Any]:
        if source.value is None:
            return {"path": None, "error": "text source requires 'value' field"}

        filename = source.filename or f"{name}.txt"
        local_path = temp_dir / "input" / filename
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(source.value)

        container_path = f"/input/{filename}"
        return {"path": container_path}