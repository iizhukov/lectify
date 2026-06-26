"""
Text to Markdown Plugin — convert text to Markdown conspectus
"""

import os
import pathlib
import tempfile
from typing import Any, Dict

from pydantic import BaseModel

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginParameter
)


class TextToMDInput(BaseModel):
    """Input for text-to-MD plugin"""
    file_id: str = ""
    txt_path: str
    prompt_id: str = ""


class TextToMDOutput(BaseModel):
    """Output from text-to-MD plugin"""
    file_id: str
    md_path: str
    char_count: int = 0


def _download_minio_to_temp(minio_url: str, max_retries: int = 5) -> str:
    """Download a minio:// URL to a temp file. Retries on eventual-consistency delays."""
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
            suffix = pathlib.Path(object_name).suffix or ".txt"
            temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
            os.close(temp_fd)
            with open(temp_path, "wb") as f:
                f.write(bytes_data)
            return temp_path
        last_error = f"Object not found in MinIO (attempt {attempt + 1}/{max_retries}): {object_name}"
        if attempt < max_retries - 1:
            _time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s, 2s, 4s, 8s
    raise FileNotFoundError(last_error)


class TextToMDPlugin(Plugin):
    """Convert transcribed text to Markdown conspectus"""

    id = "text_to_md"
    name = "Создание Markdown"
    description = "Преобразует распознанный текст в Markdown-конспект"
    version = "1.0.0"
    category = "ai"
    color = "#10b981"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 6h16M4 10h16M4 14h10M4 18h6"/></svg>'

    input_model = TextToMDInput
    output_model = TextToMDOutput

    parameters_schema = [
        PluginParameter(
            name="max_chars",
            type="int",
            description="Максимум символов для отправки в LLM",
            required=False,
            default=40000
        ),
        PluginParameter(
            name="style",
            type="string",
            description="Стиль конспекта",
            required=False,
            default="detailed",
            options=["brief", "detailed", "academic"]
        )
    ]

    async def execute(
        self,
        input_data: TextToMDInput,
        context: PluginContext,
        parameters: Dict[str, Any]
    ) -> TextToMDOutput:
        """Execute text-to-markdown"""
        file_id = input_data.file_id
        txt_path_input = input_data.txt_path
        max_chars = parameters.get("max_chars", 40000)

        context.report_progress(10, "Читаем текст...")

        txt_path = ""
        is_temp = False
        try:
            # Handle minio:// URLs — download to temp file inside Docker
            if txt_path_input.startswith("minio://"):
                txt_path = _download_minio_to_temp(txt_path_input)
                is_temp = True
            else:
                txt_path = txt_path_input

            try:
                txt_file = pathlib.Path(txt_path)
                if not txt_file.exists():
                    raise FileNotFoundError(f"Text file not found: {txt_path}")

                with open(str(txt_file), "r", encoding="utf-8") as f:
                    text = f.read()
            finally:
                # Cleanup temp file from MinIO download
                if is_temp and os.path.exists(txt_path):
                    try:
                        os.remove(txt_path)
                    except Exception:
                        pass

            context.report_progress(20, "Подготавливаем промпт...")

            # Get prompt
            prompt_id = input_data.prompt_id or "text_to_md_system"
            prompt = self._get_prompt(prompt_id, context)

            if not prompt:
                prompt = self._get_default_prompt()

            context.report_progress(30, "Отправляем в LLM...")

            # Truncate if needed
            text_to_send = text[:max_chars]

            from src.llm.client import get_llm_client
            client = get_llm_client()

            content = client.completion(
                purpose="medium",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text_to_send}
                ]
            )

            context.report_progress(80, "Сохраняем результат...")

            # Write output to /output/ for Docker, or next to input for local
            if txt_path_input.startswith("minio://"):
                md_path = "/output/result.md"
            else:
                md_path = str(pathlib.Path(txt_path).with_suffix(".md"))
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content)

            context.report_progress(100, "Markdown-конспект готов!")

            return TextToMDOutput(
                file_id=file_id,
                md_path=md_path,
                char_count=len(content)
            )

        except Exception as e:
            context.log("error", f"Text-to-MD failed: {str(e)}")
            raise

    def _get_prompt(self, prompt_id: str, context: PluginContext) -> str:
        """Get prompt from library or MinIO"""
        if context.minio_client:
            try:
                key = f"prompts/{prompt_id}.txt"
                response = context.minio_client.get_object(Bucket="lectify", Key=key)
                return response["Body"].read().decode()
            except:
                pass
        return ""

    def _get_default_prompt(self) -> str:
        """Get default prompt for MD generation"""
        return (
            "Ты — опытный методист и эксперт по структурированию учебного материала. "
            "Преобразуй следующий распознанный текст лекции в красивый, детальный и понятный конспект в формате Markdown.\n"
            "Выделяй важные термины жирным шрифтом, используй списки, логические подразделы, примеры.\n"
            "Пиши на русском языке.\n\n"
            "Текст лекции для структурирования:\n"
        )