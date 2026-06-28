"""
Text to Markdown Plugin — convert text to Markdown conspectus
"""

from typing import Any, Dict

from src.plugins.base import Plugin, PluginContext, PluginParameter, PluginOutput
from src.plugins.datasource import DataSource, OutputSource


class TextToMDOutput(PluginOutput):
    file_id: str
    md_path: str
    char_count: int = 0


class TextToMDPlugin(Plugin):
    id = "text_to_md"
    name = "Создание Markdown"
    description = "Преобразует распознанный текст в Markdown-конспект"
    version = "1.0.0"
    category = "ai"
    color = "#800080"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 6h16M4 10h16M4 14h10M4 18h6"/></svg>'

    input_model = None
    output_model = TextToMDOutput

    data_sources = {
        "txt_file": DataSource(
            type="file",
            filename="input.txt",
            required=True,
        ),
        "prompt": DataSource(
            type="prompt",
            filename="prompt.txt",
            required=False,
        ),
    }

    output_artifacts = {
        "output": OutputSource(type="file", filename="output.md"),
    }

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
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> TextToMDOutput:
        max_chars = parameters.get("max_chars", 40000)

        txt_source = context.manifest.get("txt_file")
        if txt_source is None:
            raise ValueError("data_source 'txt_file' не найден.")

        text = txt_source.read_text()

        context.report_progress(10, "Читаем текст...")

        prompt = self._get_prompt(context)
        if not prompt:
            prompt = self._get_default_prompt()

        context.report_progress(20, "Подготавливаем промпт...")

        text_to_send = text[:max_chars]

        context.report_progress(30, "Отправляем в LLM...")

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

        output_artifact = context.output.declare("output", type="file")
        with output_artifact as dst:
            dst.write(content)

        context.report_progress(100, "Markdown-конспект готов!")

        return TextToMDOutput(
            file_id="",
            md_path=str(output_artifact.path),
            char_count=len(content),
        )

    def _get_prompt(self, context: PluginContext) -> str:
        extra = context.manifest.extra("prompt")
        return extra.get("prompt_system_prompt", "") or extra.get("prompt_user_prompt_template", "")

    def _get_default_prompt(self) -> str:
        return (
            "Ты — опытный методист и эксперт по структурированию учебного материала. "
            "Преобразуй следующий распознанный текст лекции в красивый, детальный и понятный конспект в формате Markdown.\n"
            "Выделяй важные термины жирным шрифтом, используй списки, логические подразделы, примеры.\n"
            "Пиши на русском языке.\n\n"
            "Текст лекции для структурирования:\n"
        )


plugin = TextToMDPlugin
