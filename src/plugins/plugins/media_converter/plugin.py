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
            output_path = input_path.with_suffix(f".{format}")

            if input_path.suffix.lower() == f".{format}":
                context.report_progress(100, "Конвертация не требуется")
                result = MediaConverterOutput(
                    file_id=file_id,
                    media_path=str(input_path),
                    format=format,
                    duration_ms=0
                )
            else:
                audio = AudioSegment.from_file(str(input_path))
                duration_ms = len(audio)

                context.report_progress(70, "Экспортируем...")

                audio.export(
                    str(output_path),
                    format=format.replace(".", ""),
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