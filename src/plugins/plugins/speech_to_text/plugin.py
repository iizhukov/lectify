"""
Speech to Text Plugin — transcribe audio to text
"""

import pathlib
import sys
from typing import Any, Dict

from pydantic import BaseModel

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginInput,
    PluginOutput,
    PluginParameter
)


class SpeechToTextInput(BaseModel):
    """Input for speech-to-text plugin"""
    file_id: str
    media_path: str


class SpeechToTextOutput(BaseModel):
    """Output from speech-to-text plugin"""
    file_id: str
    txt_path: str
    duration_ms: int = 0
    language: str = "ru"


class SpeechToTextPlugin(Plugin):
    """Transcribe audio/video to text using Whisper"""

    id = "speech_to_text"
    name = "Распознавание речи"
    description = "Транскрибирует аудио/видео в текст"
    version = "1.0.0"
    category = "media"

    input_model = SpeechToTextInput
    output_model = SpeechToTextOutput

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
        input_data: SpeechToTextInput,
        context: PluginContext,
        parameters: Dict[str, Any]
    ) -> SpeechToTextOutput:
        """Execute speech-to-text"""
        from pydub import AudioSegment

        file_id = input_data.file_id
        file_path = input_data.media_path
        language = parameters.get("language", "ru")
        chunk_duration_ms = parameters.get("chunk_duration_minutes", 20) * 60 * 1000

        context.report_progress(10, "Загрузка аудио...")

        try:
            audio = AudioSegment.from_file(file_path)
            duration_ms = len(audio)

            context.report_progress(20, "Начинаем распознавание...")

            # Check if needs chunking
            if duration_ms <= chunk_duration_ms:
                # Single chunk
                full_text = self._transcribe_chunk(file_path, language, parameters, context)
            else:
                # Multiple chunks
                chunks = []
                for i in range(0, duration_ms, chunk_duration_ms):
                    chunks.append(audio[i:i + chunk_duration_ms])

                full_text_parts = []
                for idx, chunk in enumerate(chunks):
                    context.report_progress(
                        20 + int(60 * (idx / len(chunks))),
                        f"Распознавание части {idx + 1} из {len(chunks)}..."
                    )
                    chunk_path = pathlib.Path(file_path).parent / f"chunk_{file_id}_{idx}.mp3"
                    chunk.export(str(chunk_path), format="mp3", bitrate="64k")

                    try:
                        text = self._transcribe_chunk(str(chunk_path), language, parameters, context)
                        full_text_parts.append(text)
                    finally:
                        if chunk_path.exists():
                            chunk_path.unlink()

                full_text = " ".join(full_text_parts)

            # Save transcript
            txt_path = str(pathlib.Path(file_path).with_suffix(".txt"))
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(full_text)

            context.report_progress(100, "Распознавание завершено!")

            return SpeechToTextOutput(
                file_id=file_id,
                txt_path=txt_path,
                duration_ms=duration_ms,
                language=language
            )

        except Exception as e:
            context.log("error", f"Speech-to-text failed: {str(e)}")
            raise

    def _transcribe_chunk(self, file_path: str, language: str, parameters: Dict, context: PluginContext) -> str:
        """Transcribe a single audio chunk"""
        # This would use OpenAI Whisper API or local Whisper
        # For now, use the existing LLM client for demo
        try:
            from src.llm.client import get_llm_client
            client = get_llm_client()
            stt_model = client.get_model_name("stt")

            with open(file_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=stt_model,
                    file=audio_file,
                    language=language
                )

            return response.text

        except ImportError:
            # Fallback: return placeholder
            context.log("warning", "STT client not available, returning placeholder")
            return f"[Transcription placeholder for {file_path}]"