"""
Media Converter Plugin — converts video/audio to M4A
"""

import os
import pathlib
import tempfile
from typing import Any, Dict

from pydantic import Field

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginInput,
    PluginOutput,
    PluginParameter
)
from src.plugins.plugins.media_converter.models import (
    MediaConverterInput,
    MediaConverterOutput
)


class MediaConverterPlugin(Plugin):
    """Convert video/audio files to M4A format"""

    id = "media_converter"
    name = "Конвертация медиа"
    description = "Конвертирует видео или аудио файл в формат M4A"
    version = "1.0.0"
    category = "media"
    color = "#FF00FF"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.894L15 14M3 8.5A1.5 1.5 0 014.5 7h11A1.5 1.5 0 0117 8.5v1H3V8.5z"/></svg>'

    # FFmpeg required for media conversion
    system_packages = ["ffmpeg"]

    input_model = MediaConverterInput
    output_model = MediaConverterOutput

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
        input_data: MediaConverterInput,
        context: PluginContext,
        parameters: Dict[str, Any]
    ) -> MediaConverterOutput:
        """
        Execute media conversion.

        For Docker execution, this runs inside a container.
        For local development, it runs directly.
        """
        file_id = input_data.file_id
        file_path = input_data.file_path
        format = parameters.get("format", "m4a")
        bitrate = parameters.get("bitrate", "64k")

        context.report_progress(10, "Начинаем конвертацию...")

        try:
            # Check if MinIO path
            if file_path.startswith("minio://"):
                context.report_progress(20, "Скачиваем файл из MinIO...")
                local_path = self._download_from_minio(file_path, file_id, context)
                should_cleanup = True
            else:
                local_path = file_path
                should_cleanup = False

            context.report_progress(40, "Конвертируем файл...")

            # Convert using pydub
            from pydub import AudioSegment

            input_path = pathlib.Path(local_path)

            # When running in Docker, /input/ is read-only — write output to /output/
            if str(input_path).startswith("/input/"):
                stem = input_path.stem
                output_path = pathlib.Path("/output") / f"{stem}.{format}"
            else:
                output_path = input_path.with_suffix(f".{format}")

            if input_path.suffix.lower() == f".{format}":
                context.report_progress(80, "Конвертация не требуется, копируем файл...")
                # Copy file to /output/ even if no conversion needed
                # so ContainerRunnerOrchestrator can upload it to MinIO
                stem = input_path.stem
                output_path = pathlib.Path("/output") / f"{stem}.{format}"
                import shutil
                shutil.copy2(str(input_path), str(output_path))

                # Get duration for metadata
                audio = AudioSegment.from_file(str(input_path))
                duration_ms = len(audio)

                context.report_progress(100, "Готово!")
                result = MediaConverterOutput(
                    file_id=file_id,
                    media_path=str(output_path),
                    format=format,
                    duration_ms=duration_ms
                )
            else:
                audio = AudioSegment.from_file(str(input_path))
                duration_ms = len(audio)

                context.report_progress(70, "Экспортируем...")

                audio.export(
                    str(output_path),
                    format="ipod" if format == "m4a" else format.replace(".", ""),
                    bitrate=bitrate
                )

                context.report_progress(100, f"Готово! Файл: {output_path.name}")

                result = MediaConverterOutput(
                    file_id=file_id,
                    media_path=str(output_path),
                    format=format,
                    duration_ms=duration_ms
                )

            # Cleanup temp file
            if should_cleanup and os.path.exists(local_path):
                os.remove(local_path)

            return result

        except Exception as e:
            context.log("error", f"Ошибка конвертации: {str(e)}")
            raise

    def _download_from_minio(self, minio_path: str, file_id: str, context: PluginContext) -> str:
        """Download file from MinIO"""
        object_name = minio_path.replace("minio://", "")
        temp_dir = tempfile.gettempdir()
        local_path = os.path.join(temp_dir, f"{file_id}_{os.path.basename(object_name)}")

        if context.minio_client:
            context.minio_client.fget_object(
                Bucket="lectify",
                Key=object_name,
                Filename=local_path
            )

        return local_path


# Export for registry
plugin = MediaConverterPlugin