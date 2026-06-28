"""
Text to LaTeX Plugin — convert text to LaTeX conspectus
"""

from typing import Any, Dict

from src.plugins.base import Plugin, PluginContext, PluginParameter, PluginOutput
from src.plugins.datasource import DataSource, OutputSource


class TextToLatexOutput(PluginOutput):
    file_id: str
    latex_path: str


class TextToLatexPlugin(Plugin):
    id = "text_to_latex"
    name = "Создание LaTeX"
    description = "Преобразует распознанный текст в LaTeX-конспект"
    version = "1.0.0"
    category = "ai"
    color = "#f59e0b"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"/></svg>'

    input_model = None
    output_model = TextToLatexOutput

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
        "output": OutputSource(type="file", filename="output.tex"),
    }

    parameters_schema = [
        PluginParameter(
            name="segments",
            type="int",
            description="Количество сегментов",
            required=False,
            default=3
        ),
        PluginParameter(
            name="subject",
            type="string",
            description="Предмет (для промпта)",
            required=False,
            default="auto",
            options=["auto", "chemistry", "history", "math", "physics", "sociology"]
        )
    ]

    async def execute(
        self,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> TextToLatexOutput:
        subject = parameters.get("subject", "auto")

        txt_source = context.manifest.get("txt_file")
        if txt_source is None:
            raise ValueError("data_source 'txt_file' не найден.")

        text = txt_source.read_text()

        context.report_progress(10, "Читаем текст...")

        if subject == "auto":
            context.report_progress(20, "Определяем предмет...")
            subject = self._detect_subject(text)

        context.report_progress(30, f"Генерируем LaTeX ({subject})...")

        prompt = self._get_prompt(context, subject)
        if not prompt:
            prompt = self._get_default_prompt(subject)

        context.report_progress(40, "Отправляем в LLM...")

        from src.llm.client import get_llm_client
        client = get_llm_client()

        latex_content = client.completion(
            purpose="smart",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ]
        )

        latex_content = latex_content.strip()
        if latex_content.startswith("```latex"):
            latex_content = latex_content[8:]
        if latex_content.startswith("```"):
            latex_content = latex_content[3:]
        if latex_content.endswith("```"):
            latex_content = latex_content[:-3]
        latex_content = latex_content.strip()

        context.report_progress(80, "Проверяем LaTeX...")

        if not self._validate_latex(latex_content):
            context.log("warning", "LaTeX validation failed - document may have issues")

        context.report_progress(90, "Сохраняем результат...")

        output_artifact = context.output.declare("output", type="file")
        with output_artifact as dst:
            dst.write(latex_content)

        context.report_progress(100, "LaTeX-конспект готов!")

        return TextToLatexOutput(
            file_id="",
            latex_path=str(output_artifact.path),
        )

    def _get_prompt(self, context: PluginContext, _subject: str) -> str:
        extra = context.manifest.extra("prompt")
        return extra.get("prompt_system_prompt", "") or extra.get("prompt_user_prompt_template", "")

    def _validate_latex(self, latex_content: str) -> bool:
        try:
            has_documentclass = r'\documentclass' in latex_content
            has_begin_doc = r'\begin{document}' in latex_content
            has_end_doc = r'\end{document}' in latex_content

            open_braces = latex_content.count('{')
            close_braces = latex_content.count('}')
            balanced = open_braces == close_braces

            return has_documentclass and has_begin_doc and has_end_doc and balanced
        except Exception:
            return False

    def _detect_subject(self, text: str) -> str:
        try:
            first_100 = " ".join(text.split()[:100])

            from src.llm.client import get_llm_client
            client = get_llm_client()

            classifier_prompt = (
                "Ты — эксперт по категоризации учебного контента. "
                "Определи, к какому предмету относится текст: chemistry, history, math, physics, sociology.\n"
                "Если не уверен, верни 'sys_prompt'\n\nТекст:"
            )

            subject = client.completion(
                purpose="smart",
                messages=[
                    {"role": "system", "content": classifier_prompt},
                    {"role": "user", "content": first_100}
                ]
            ).strip()

            valid = ["chemistry", "history", "math", "physics", "sociology", "sys_prompt"]
            if subject not in valid:
                subject = "sys_prompt"

            return subject

        except Exception:
            return "sys_prompt"

    def _get_default_prompt(self, _subject: str) -> str:
        base_prompt = (
            "Ты — эксперт по созданию учебных материалов в LaTeX. "
            "Преобразуй следующий текст лекции в красиво оформленный LaTeX-документ.\n\n"
            "Требования:\n"
            "- Используй \\documentclass{article}\n"
            "- Добавь необходимые пакеты (babel, fontenc, inputenc для русского языка)\n"
            "- Структурируй текст с помощью \\section, \\subsection\n"
            "- Выделяй важные термины (\\textbf, \\emph)\n"
            "- Используй списки (itemize, enumerate) где уместно\n"
            "- Для формул используй math mode\n"
            "- Создай полный компилируемый документ\n\n"
        )

        subject_hints = {
            "math": "Используй математические окружения (equation, align) для всех формул.",
            "physics": "Используй физические обозначения и формулы (siunitx пакет).",
            "chemistry": "Используй chemfig для химических формул.",
            "history": "Фокусируйся на датах, событиях и исторических персонажах.",
            "sociology": "Выделяй концепции, теории и авторов."
        }

        hint = subject_hints.get(_subject, "")
        if hint:
            base_prompt += hint + "\n\n"

        base_prompt += "Текст лекции для преобразования:\n"
        return base_prompt


plugin = TextToLatexPlugin
