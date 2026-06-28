"""
Input Plugin - динамический источник данных для workflow

Плагин-источник для передачи файлов в граф.
Данные читаются из /input/ (записаны InputResolver через data_sources).
"""
from typing import Any, Dict

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginParameter,
)
from src.plugins.plugins.input.models import InputPluginOutput


_INPUT_TYPE_MIME = {
    "audio": ["audio/"],
    "video": ["video/"],
    "pdf": ["application/pdf"],
    "text": ["text/"],
    "image": ["image/"],
}


class InputPlugin(Plugin):
    id = "input"
    name = "Входные данные"
    description = "Источник данных для workflow - передаёт файл дальше по графу"
    version = "1.0.0"
    category = "io"
    color = "#10b981"
    icon_svg = (
        '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>'
        '</svg>'
    )

    input_model: Any = None
    output_model = InputPluginOutput

    parameters_schema = [
        PluginParameter(
            name="input_type",
            type="string",
            description="Тип ожидаемого файла",
            required=True,
            default="any",
            options=["audio", "video", "pdf", "text", "image", "any"],
        ),
    ]

    async def execute(
        self,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> InputPluginOutput:
        input_type = parameters.get("input_type", "any")

        source = context.manifest.get("file_id")
        if source is None:
            raise ValueError(
                "data_source 'file_id' не найден. "
                "Проверьте что input_files при создании execution содержит '{node_id}': 'file-...'."
            )

        file_id = source.read_text().strip()

        if input_type != "any" and input_type in _INPUT_TYPE_MIME:
            mime = source.mime_type
            allowed = _INPUT_TYPE_MIME[input_type]
            if not any(mime.startswith(p) for p in allowed):
                raise ValueError(
                    f"Несовместимый тип файла: ожидался '{input_type}' (MIME: {allowed}), "
                    f"получен '{mime}' для файла '{source.name}'."
                )

        context.report_progress(100, f"Файл загружен: {file_id}")

        return InputPluginOutput(
            file_id=file_id,
            input_type=input_type,
        )
