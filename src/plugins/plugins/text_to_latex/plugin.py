"""
Text to LaTeX Plugin — convert text to LaTeX conspectus
"""

import os
import pathlib
import re
import tempfile
from typing import Any, Dict

from pydantic import BaseModel

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginParameter
)


class TextToLatexInput(BaseModel):
    """Input for text-to-LaTeX plugin"""
    file_id: str = ""
    txt_path: str
    prompt_id: str = ""


class TextToLatexOutput(BaseModel):
    """Output from text-to-LaTeX plugin"""
    file_id: str
    latex_path: str


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
            _time.sleep(0.5 * (2 ** attempt))
    raise FileNotFoundError(last_error)


class TextToLatexPlugin(Plugin):
    """Convert transcribed text to LaTeX conspectus"""

    id = "text_to_latex"
    name = "Создание LaTeX"
    description = "Преобразует распознанный текст в LaTeX-конспект"
    version = "1.0.0"
    category = "ai"
    color = "#f59e0b"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"/></svg>'

    input_model = TextToLatexInput
    output_model = TextToLatexOutput

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
        input_data: TextToLatexInput,
        context: PluginContext,
        parameters: Dict[str, Any]
    ) -> TextToLatexOutput:
        """Execute text-to-latex"""
        file_id = input_data.file_id
        txt_path_input = input_data.txt_path
        subject = parameters.get("subject", "auto")

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

            # Detect subject if auto
            if subject == "auto":
                context.report_progress(20, "Определяем предмет...")
                subject = self._detect_subject(text, context)

            context.report_progress(30, f"Генерируем LaTeX ({subject})...")

            # Get prompt
            prompt_id = input_data.prompt_id or f"text_to_latex_{subject}"
            prompt = self._get_prompt(prompt_id)

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

            # Clean markdown code blocks if present
            latex_content = latex_content.strip()
            if latex_content.startswith("```latex"):
                latex_content = latex_content[8:]
            if latex_content.startswith("```"):
                latex_content = latex_content[3:]
            if latex_content.endswith("```"):
                latex_content = latex_content[:-3]
            latex_content = latex_content.strip()

            context.report_progress(80, "Проверяем LaTeX...")

            # Validate LaTeX
            if not self._validate_latex(latex_content):
                context.log("warning", "LaTeX validation failed - document may have issues")

            context.report_progress(90, "Сохраняем результат...")

            # Determine output path
            if txt_path_input.startswith("minio://") or txt_path.startswith("/input/"):
                base_name = pathlib.Path(txt_path).stem if not txt_path_input.startswith("minio://") else "result"
                latex_path = f"/output/{base_name}.tex"
            else:
                latex_path = str(pathlib.Path(txt_path).with_suffix(".tex"))

            with open(latex_path, "w", encoding="utf-8") as f:
                f.write(latex_content)

            context.report_progress(100, "LaTeX-конспект готов!")

            return TextToLatexOutput(
                file_id=file_id,
                latex_path=latex_path
            )

        except Exception as e:
            context.log("error", f"Text-to-LaTeX failed: {str(e)}")
            raise

    def _validate_latex(self, latex_content: str) -> bool:
        """Basic LaTeX validation"""
        try:
            # Check for required LaTeX structure
            has_documentclass = r'\documentclass' in latex_content
            has_begin_doc = r'\begin{document}' in latex_content
            has_end_doc = r'\end{document}' in latex_content

            # Check balanced braces
            open_braces = latex_content.count('{')
            close_braces = latex_content.count('}')
            balanced = open_braces == close_braces

            return has_documentclass and has_begin_doc and has_end_doc and balanced
        except Exception:
            return False

    def _detect_subject(self, text: str, context: PluginContext) -> str:
        """Detect subject using LLM"""
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

        except:
            return "sys_prompt"

    def _get_prompt(self, prompt_id: str) -> str:
        """Get prompt from library or MinIO"""
        try:
            from src.db.database import SessionLocal
            from src.db.entity import DBPrompt
            session = SessionLocal()
            try:
                prompt = session.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()
                if prompt:
                    return str(prompt.system_prompt or "")
            finally:
                session.close()
        except:
            pass
        return ""

    def _get_default_prompt(self, subject: str) -> str:
        """Get default prompt for LaTeX generation"""
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

        hint = subject_hints.get(subject, "")
        if hint:
            base_prompt += hint + "\n\n"

        base_prompt += "Текст лекции для преобразования:\n"
        return base_prompt
