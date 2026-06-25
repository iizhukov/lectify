"""
Text to LaTeX Plugin — convert text to LaTeX conspectus
"""

import pathlib
import subprocess
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


class TextToLatexInput(BaseModel):
    """Input for text-to-LaTeX plugin"""
    file_id: str
    txt_path: str


class TextToLatexOutput(BaseModel):
    """Output from text-to-LaTeX plugin"""
    file_id: str
    latex_path: str


class TextToLatexPlugin(Plugin):
    """Convert transcribed text to LaTeX conspectus"""

    id = "text_to_latex"
    name = "Создание LaTeX"
    description = "Преобразует распознанный текст в LaTeX-конспект"
    version = "1.0.0"
    category = "ai"

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
        txt_path = input_data.txt_path
        segments = parameters.get("segments", 3)
        subject = parameters.get("subject", "auto")

        context.report_progress(10, "Читаем текст...")

        try:
            txt_file = pathlib.Path(txt_path)
            if not txt_file.exists():
                raise FileNotFoundError(f"Text file not found: {txt_path}")

            # Detect subject if auto
            if subject == "auto":
                context.report_progress(20, "Определяем предмет...")
                subject = self._detect_subject(str(txt_file), context)

            context.report_progress(30, f"Генерируем LaTeX ({subject})...")

            # Build script path (in same directory as this plugin)
            script_path = pathlib.Path(__file__).parent.parent.parent.parent / "text_to_latex.py"

            res = subprocess.run(
                [
                    sys.executable, str(script_path),
                    "--file", str(txt_file),
                    "--seg-num", str(segments),
                    "--sys-prompt", f"resources/prompts/{subject}.txt",
                    "--language", "ru-RU"
                ],
                capture_output=True,
                text=True
            )

            if res.returncode != 0:
                raise Exception(f"Script failed: {res.stderr or res.stdout}")

            latex_path = str(txt_file.with_suffix(".tex"))
            if not pathlib.Path(latex_path).exists():
                raise Exception("LaTeX file was not created")

            context.report_progress(100, "LaTeX-конспект готов!")

            return TextToLatexOutput(
                file_id=file_id,
                latex_path=latex_path
            )

        except Exception as e:
            context.log("error", f"Text-to-LaTeX failed: {str(e)}")
            raise

    def _detect_subject(self, txt_path: str, context: PluginContext) -> str:
        """Detect subject using LLM"""
        try:
            txt_file = pathlib.Path(txt_path)
            with open(str(txt_file), "r", encoding="utf-8") as f:
                text = f.read()
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
