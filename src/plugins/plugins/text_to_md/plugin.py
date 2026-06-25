"""
Text to Markdown Plugin — convert text to Markdown conspectus
"""

import pathlib
from typing import Any, Dict

from pydantic import BaseModel

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginInput,
    PluginOutput,
    PluginParameter
)


class TextToMDInput(BaseModel):
    """Input for text-to-MD plugin"""
    file_id: str
    txt_path: str
    prompt_id: str = ""


class TextToMDOutput(BaseModel):
    """Output from text-to-MD plugin"""
    file_id: str
    md_path: str
    char_count: int = 0


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
        txt_path = input_data.txt_path
        max_chars = parameters.get("max_chars", 40000)

        context.report_progress(10, "Читаем текст...")

        try:
            txt_file = pathlib.Path(txt_path)
            if not txt_file.exists():
                raise FileNotFoundError(f"Text file not found: {txt_path}")

            with open(str(txt_file), "r", encoding="utf-8") as f:
                text = f.read()

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

            md_path = str(txt_file.with_suffix(".md"))
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