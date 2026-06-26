"""
Speech to Text Plugin — transcribe audio to text
"""

import os
import pathlib
import sys
import tempfile
from typing import Any, Dict

from pydantic import BaseModel

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginInput,
    PluginOutput,
    PluginParameter
)


# Whisper API max file size per request — 20MB leaves margin under the ~25MB limit
MAX_CHUNK_SIZE_BYTES = 20 * 1024 * 1024
# Fixed time step for size-based sub-chunking (5 minutes)
_SIZE_SUB_CHUNK_MS = 5 * 60 * 1000


class SpeechToTextInput(BaseModel):
    """Input for speech-to-text plugin"""
    file_id: str = ""
    media_path: str


def _download_minio_to_temp(minio_url: str, max_retries: int = 5) -> tuple[str, bool]:
    """Download a minio:// URL to a temp file. Retries on eventual-consistency delays.
    Returns (temp_path, is_temp_file)."""
    import time as _time
    object_name = minio_url.replace("minio://", "")
    from src.utils.storage import MinIOStorage
    storage = MinIOStorage()
    if object_name.startswith(storage.artifacts_bucket + "/"):
        object_name = object_name[len(storage.artifacts_bucket) + 1:]
    last_error = None
    for attempt in range(max_retries):
        bytes_data = storage.get_file_bytes(object_name)
        if bytes_data:
            suffix = pathlib.Path(object_name).suffix or ".m4a"
            temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
            os.close(temp_fd)
            with open(temp_path, "wb") as f:
                f.write(bytes_data)
            return temp_path, True
        last_error = f"Object not found in MinIO (attempt {attempt + 1}/{max_retries}): {object_name}"
        if attempt < max_retries - 1:
            _time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s, 2s, 4s, 8s
    raise FileNotFoundError(last_error)


def _resolve_audio_path(file_id: str, media_path: str) -> tuple[str, bool]:
    """
    Resolve audio file path: prefer DBFile lookup, fall back to minio:// URL.
    Returns (resolved_path, is_temp_file).
    """
    def _try_download(object_name: str) -> tuple[str, bool]:
        from src.utils.storage import MinIOStorage
        storage = MinIOStorage()
        last_error = None
        for attempt in range(5):
            bytes_data = storage.get_file_bytes(object_name)
            if bytes_data:
                suffix = pathlib.Path(object_name).suffix or ".m4a"
                temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
                os.close(temp_fd)
                with open(temp_path, "wb") as f:
                    f.write(bytes_data)
                return temp_path, True
            last_error = f"Object not found in MinIO (attempt {attempt + 1}/5): {object_name}"
            if attempt < 4:
                import time as _time
                _time.sleep(0.5 * (2 ** attempt))
        raise FileNotFoundError(last_error)

    # 1. Try DBFile lookup by file_id
    try:
        from src.db.database import SessionLocal
        from src.db.entity import DBFile

        session = SessionLocal()
        try:
            db_file = session.query(DBFile).filter(DBFile.id == file_id).first()
            minio_path_val = getattr(db_file, "minio_path", None) if db_file else None
            if minio_path_val:
                return _try_download(minio_path_val)
        finally:
            session.close()
    except FileNotFoundError:
        pass

    # 2. Fall back to minio:// URL in media_path
    if media_path.startswith("minio://"):
        object_name = media_path.replace("minio://", "")
        try:
            return _try_download(object_name)
        except FileNotFoundError:
            pass

    # 3. Last resort: use as local path
    return media_path, False


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
    color = "#8b5cf6"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"/></svg>'

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
        media_path = input_data.media_path
        language = parameters.get("language", "ru")
        chunk_duration_ms = parameters.get("chunk_duration_minutes", 20) * 60 * 1000

        context.report_progress(10, "Загрузка аудио...")

        audio_path = ""
        is_temp = False
        try:
            # Handle minio:// URLs directly — file_id may be empty for upstream node outputs
            if media_path.startswith("minio://"):
                audio_path, is_temp = _download_minio_to_temp(media_path)
            else:
                audio_path = media_path
            audio = AudioSegment.from_file(audio_path)
            duration_ms = len(audio)

            context.report_progress(20, "Начинаем распознавание...")

            # Check if needs chunking
            if duration_ms <= chunk_duration_ms:
                # Single chunk — but also check file size
                if os.path.getsize(audio_path) > MAX_CHUNK_SIZE_BYTES:
                    full_text = self._transcribe_with_size_split(
                        audio_path, language, parameters, context
                    )
                else:
                    full_text = self._transcribe_chunk(audio_path, language, parameters, context)
            else:
                # Time-based chunking — each chunk additionally checked for size
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
                    chunk_path = pathlib.Path(tempfile.gettempdir()) / f"chunk_{file_id}_{idx}.mp3"
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

            # Save transcript — write to /output/ for Docker, next to audio for local
            output_path = pathlib.Path(audio_path)
            if str(output_path).startswith("/input/") or str(output_path).startswith("/tmp/"):
                txt_path = str(pathlib.Path("/output") / output_path.with_suffix(".txt").name)
            else:
                txt_path = str(output_path.with_suffix(".txt"))
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
        finally:
            # Cleanup temp file created by _resolve_audio_path
            try:
                if is_temp and audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception:
                pass

    def _transcribe_with_size_split(
        self,
        file_path: str,
        language: str,
        parameters: Dict,
        context: PluginContext,
    ) -> str:
        """
        Split audio file by size and transcribe each part.
        Re-chunks the file until each part is under MAX_CHUNK_SIZE_BYTES.
        """
        from pydub import AudioSegment

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
        """Transcribe a single audio chunk via OpenAI Whisper API."""
        import io
        from pydub import AudioSegment
        from src.llm.client import get_llm_client

        llm = get_llm_client()
        stt_model = llm.get_model_name("stt")
        openai_client = llm.get_client()

        # Re-export to MP3 to guarantee format and reduce size, write to a real temp file
        audio = AudioSegment.from_file(file_path)
        tmp_mp3 = pathlib.Path(tempfile.gettempdir()) / f"stt_{pathlib.Path(file_path).stem}_{id(audio)}.mp3"
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