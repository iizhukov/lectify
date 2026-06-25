"""
LaTeX to PDF Plugin — compile LaTeX to PDF
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


class LatexToPDFInput(BaseModel):
    """Input for LaTeX-to-PDF plugin"""
    file_id: str
    latex_path: str


class LatexToPDFOutput(BaseModel):
    """Output from LaTeX-to-PDF plugin"""
    file_id: str
    pdf_path: str
    attempts: int = 1


class LatexToPDFPlugin(Plugin):
    """Compile LaTeX file to PDF"""

    id = "latex_to_pdf"
    name = "Компиляция PDF"
    description = "Компилирует LaTeX-файл в PDF с автоисправлением ошибок"
    version = "1.0.0"
    category = "media"

    input_model = LatexToPDFInput
    output_model = LatexToPDFOutput

    parameters_schema = [
        PluginParameter(
            name="max_attempts",
            type="int",
            description="Максимум попыток автоисправления",
            required=False,
            default=3
        ),
        PluginParameter(
            name="use_llm_repair",
            type="bool",
            description="Использовать LLM для исправления ошибок",
            required=False,
            default=True
        )
    ]

    async def execute(
        self,
        input_data: LatexToPDFInput,
        context: PluginContext,
        parameters: Dict[str, Any]
    ) -> LatexToPDFOutput:
        """Execute LaTeX-to-PDF"""
        file_id = input_data.file_id
        latex_path = input_data.latex_path
        max_attempts = parameters.get("max_attempts", 3)
        use_llm_repair = parameters.get("use_llm_repair", True)

        context.report_progress(10, "Проверяем файл...")

        try:
            latex_file = pathlib.Path(latex_path)
            if not latex_file.exists():
                raise FileNotFoundError(f"LaTeX file not found: {latex_path}")

            # Build script path
            script_path = pathlib.Path(__file__).parent.parent.parent.parent / "latex_to_pdf.py"

            attempts = 0
            while attempts < max_attempts:
                attempts += 1
                context.report_progress(
                    20 + int(30 * (attempts - 1) / max_attempts),
                    f"Компиляция (попытка {attempts}/{max_attempts})..."
                )

                res = subprocess.run(
                    [
                        sys.executable, str(script_path),
                        "--file", str(latex_file),
                        "--clean"
                    ],
                    capture_output=True,
                    text=True
                )

                if res.returncode == 0:
                    break

                # Compilation failed, try LLM repair
                if use_llm_repair and attempts < max_attempts:
                    context.report_progress(
                        50,
                        f"Компиляция не удалась. Исправляем через LLM ({attempts})..."
                    )
                    self._repair_latex(latex_file, res.stderr or res.stdout, context)

            if res.returncode != 0:
                raise Exception(f"PDF compilation failed after {attempts} attempts")

            pdf_path = str(latex_file.with_suffix(".pdf"))
            if not pathlib.Path(pdf_path).exists():
                raise Exception("PDF file was not created")

            context.report_progress(100, "PDF готов!")

            return LatexToPDFOutput(
                file_id=file_id,
                pdf_path=pdf_path,
                attempts=attempts
            )

        except Exception as e:
            context.log("error", f"LaTeX-to-PDF failed: {str(e)}")
            raise

    def _repair_latex(self, latex_file: pathlib.Path, error_log: str, context: PluginContext):
        """Repair LaTeX using LLM"""
        try:
            from src.llm.client import get_llm_client
            client = get_llm_client()

            with open(str(latex_file), "r", encoding="utf-8") as f:
                latex_code = f.read()

            repair_prompt = (
                "Ты — эксперт по верстке документов в LaTeX. "
                "Проанализируй лог ошибок и исправь LaTeX-код. "
                "Верни ТОЛЬКО исправленный код без комментариев."
            )

            context_chunk = latex_code[:25000]
            llm_prompt = f"Лог ошибок:\n{error_log}\n\nКод:\n{context_chunk}"

            fixed_latex = client.completion(
                purpose="smart",
                messages=[
                    {"role": "system", "content": repair_prompt},
                    {"role": "user", "content": llm_prompt}
                ]
            )

            # Clean markdown code blocks
            fixed_latex = fixed_latex.strip()
            if fixed_latex.startswith("```latex"):
                fixed_latex = fixed_latex[8:]
            if fixed_latex.startswith("```"):
                fixed_latex = fixed_latex[3:]
            if fixed_latex.endswith("```"):
                fixed_latex = fixed_latex[:-3]
            fixed_latex = fixed_latex.strip()

            with open(str(latex_file), "w", encoding="utf-8") as f:
                f.write(fixed_latex)

        except Exception as e:
            context.log("warning", f"LaTeX repair failed: {e}")