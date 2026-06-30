"""
Media Converter Plugin — converts video/audio to M4A
"""

from pathlib import Path
from typing import Any, Dict

from pydub import AudioSegment

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginParameter,
)
from src.plugins.datasource import DataSource, OutputSource
from src.plugins.plugins.media_converter.models import (
    MediaConverterInput,
    MediaConverterOutput,
)


class MediaConverterPlugin(Plugin):
    id = "media_converter"
    name = "Конвертация медиа"
    description = "Конвертирует видео или аудио файл в формат M4A"
    version = "1.0.0"
    category = "media"
    color = "#FF00FF"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.894L15 14M3 8.5A1.5 1.5 0 014.5 7h11A1.5 1.5 0 0117 8.5v1H3V8.5z"/></svg>'

    system_packages = ["ffmpeg"]

    input_model = MediaConverterInput
    output_model = MediaConverterOutput

    data_sources = {
        "file": DataSource(
            type="file",
            source="file_id",
            required=True,
        ),
    }

    output_artifacts = {
        "output": OutputSource(type="file", filename="output.m4a", target_field="file_id"),
    }

    parameters_schema = [
        PluginParameter(
            name="format",
            type="string",
            description="Выходной формат",
            required=False,
            default="m4a",
            options=["m4a", "mp3", "wav"]
        ),
        PluginParameter(
            name="bitrate",
            type="string",
            description="Битрейт аудио",
            required=False,
            default="64k",
            options=["32k", "64k", "128k", "256k"]
        ),
        PluginParameter(
            name="sample_rate",
            type="int",
            description="Частота дискретизации (Hz)",
            required=False,
            default=44100,
            options=[22050, 44100, 48000]
        )
    ]

    async def execute(
        self,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> MediaConverterOutput:
        output_format = parameters.get("format", "m4a")
        bitrate = parameters.get("bitrate", "64k")

        source = context.manifest.get("file")
        if source is None:
            raise ValueError("data_source 'file' не найден.")

        input_path = Path(source.path)
        input_suffix = input_path.suffix.lower().lstrip(".")
        output_suffix = output_format.lower().lstrip(".")

        context.report_progress(10, "Начинаем конвертацию...")

        output_artifact = context.output.declare("output", type="file")
        output_path_str = str(output_artifact.path)

        if input_suffix == output_suffix:
            context.report_progress(80, "Конвертация не требуется, копируем файл...")
            with Path(source.path).open("rb") as src, output_artifact as dst:
                dst.write(src.read())

            context.report_progress(100, "Готово!")
            return MediaConverterOutput(
                file_id="",
                format=output_format,
                duration_ms=0,
            )

        context.report_progress(40, "Конвертируем файл...")

        audio = AudioSegment.from_file(str(input_path))
        duration_ms = len(audio)

        context.report_progress(70, "Экспортируем...")

        export_format = "ipod" if output_format == "m4a" else output_suffix
        audio.export(output_path_str, format=export_format, bitrate=bitrate)

        context.report_progress(100, f"Готово! Файл: {output_artifact.name}")

        return MediaConverterOutput(
            file_id="",
            format=output_format,
            duration_ms=duration_ms,
        )


plugin = MediaConverterPlugin
