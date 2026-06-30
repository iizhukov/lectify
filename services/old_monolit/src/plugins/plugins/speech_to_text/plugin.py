import os
import pathlib
import tempfile

from typing import Any, Dict

import tempfile as tf
from pydub import AudioSegment

from src.llm.client import get_llm_client
from src.plugins.base import Plugin, PluginContext, PluginParameter
from src.plugins.datasource import DataSource, OutputSource
from src.plugins.plugins.speech_to_text.models import SpeechToTextInput, SpeechToTextOutput


MAX_CHUNK_SIZE_BYTES = 20 * 1024 * 1024
_SIZE_SUB_CHUNK_MS = 5 * 60 * 1000


class SpeechToTextPlugin(Plugin):
    id = "speech_to_text"
    name = "Распознавание речи"
    description = "Транскрибирует аудио/видео в текст"
    version = "1.0.0"
    category = "media"
    color = "#8b5cf6"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"/></svg>'

    system_packages = ["ffmpeg"]

    input_model = SpeechToTextInput
    output_model = SpeechToTextOutput

    data_sources = {
        "audio_file": DataSource(
            type="file",
            source="file_id",
            filename="audio.m4a",
            required=True,
        ),
    }

    output_artifacts = {
        "output": OutputSource(type="file", filename="transcript.txt", target_field="file_id"),
    }

    parameters_schema = [
        PluginParameter(
            name="model",
            type="string",
            description="Модель Whisper",
            required=False,
            default="base",
            options=["tiny", "base", "small", "medium", "large"]
        ),
        PluginParameter(
            name="language",
            type="string",
            description="Язык аудио",
            required=False,
            default="ru"
        ),
        PluginParameter(
            name="chunk_duration_minutes",
            type="int",
            description="Длительность чанка (минуты)",
            required=False,
            default=20
        )
    ]

    async def execute(
        self,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> SpeechToTextOutput:
        source = context.manifest.get("audio_file")
        if source is None:
            raise ValueError("data_source 'audio_file' не найден.")

        audio_path_str = source.path
        language = parameters.get("language", "ru")
        chunk_duration_ms = parameters.get("chunk_duration_minutes", 20) * 60 * 1000

        context.report_progress(10, "Загрузка аудио...")

        audio = AudioSegment.from_file(audio_path_str)
        duration_ms = len(audio)

        context.report_progress(20, "Начинаем распознавание...")

        if duration_ms <= chunk_duration_ms:
            if os.path.getsize(audio_path_str) > MAX_CHUNK_SIZE_BYTES:
                full_text = self._transcribe_with_size_split(
                    audio_path_str, language, parameters, context
                )
            else:
                full_text = self._transcribe_chunk(audio_path_str, language, parameters, context)
        else:
            chunks = []
            for i in range(0, duration_ms, chunk_duration_ms):
                chunks.append(audio[i:i + chunk_duration_ms])

            full_text_parts = []
            total_chunks = len(chunks)
            for idx, chunk in enumerate(chunks):
                context.report_progress(
                    20 + int(60 * (idx / total_chunks)),
                    f"Распознавание части {idx + 1} из {total_chunks}..."
                )
                chunk_path = pathlib.Path(tempfile.gettempdir()) / f"chunk_{idx}.mp3"
                chunk.export(str(chunk_path), format="mp3", bitrate="64k")

                try:
                    if chunk_path.stat().st_size > MAX_CHUNK_SIZE_BYTES:
                        text = self._transcribe_with_size_split(
                            str(chunk_path), language, parameters, context
                        )
                    else:
                        text = self._transcribe_chunk(str(chunk_path), language, parameters, context)
                    full_text_parts.append(text)
                finally:
                    if chunk_path.exists():
                        chunk_path.unlink()

            full_text = " ".join(full_text_parts)

        context.report_progress(90, "Сохраняем результат...")

        output_artifact = context.output.declare("output", type="file")
        with output_artifact as dst:
            dst.write(full_text)

        context.report_progress(100, "Распознавание завершено!")

        return SpeechToTextOutput(
            file_id="",
            txt_path=str(output_artifact.path),
            duration_ms=duration_ms,
            language=language,
        )

    def _transcribe_with_size_split(
        self,
        file_path: str,
        language: str,
        parameters: Dict,
        context: PluginContext,
    ) -> str:
        audio = AudioSegment.from_file(file_path)
        base_path = pathlib.Path(file_path)
        parts = []
        idx = 0

        for start_ms in range(0, len(audio), _SIZE_SUB_CHUNK_MS):
            chunk = audio[start_ms:start_ms + _SIZE_SUB_CHUNK_MS]
            chunk_path = pathlib.Path(tempfile.gettempdir()) / f"size_chunk_{base_path.stem}_{idx}.mp3"
            chunk.export(str(chunk_path), format="mp3", bitrate="64k")

            try:
                if chunk_path.stat().st_size > MAX_CHUNK_SIZE_BYTES:
                    parts.append(
                        self._transcribe_with_size_split(str(chunk_path), language, parameters, context)
                    )
                else:
                    parts.append(self._transcribe_chunk(str(chunk_path), language, parameters, context))
            finally:
                if chunk_path.exists():
                    chunk_path.unlink()

            idx += 1

        return " ".join(parts)

    def _transcribe_chunk(self, file_path: str, language: str, parameters: Dict, context: PluginContext) -> str:
        llm = get_llm_client()
        stt_model = llm.get_model_name("stt")
        openai_client = llm.get_client()

        audio = AudioSegment.from_file(file_path)
        tmp_mp3 = pathlib.Path(tf.gettempdir()) / f"stt_{pathlib.Path(file_path).stem}_{id(audio)}.mp3"
        audio.export(str(tmp_mp3), format="mp3", bitrate="64k")
        try:
            with open(str(tmp_mp3), "rb") as f:
                kwargs = {"model": stt_model, "file": (tmp_mp3.name, f, "audio/mpeg")}
                if language and language != "auto":
                    kwargs["language"] = language
                response = openai_client.audio.transcriptions.create(**kwargs)
        finally:
            if tmp_mp3.exists():
                tmp_mp3.unlink()

        return response.text


plugin = SpeechToTextPlugin
