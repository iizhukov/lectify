"""
LaTeX to PDF Plugin — compile LaTeX to PDF
"""
import os
from pathlib import Path
import subprocess
import tempfile
import shutil

from typing import Any, Dict

from src.plugins.base import Plugin, PluginContext, PluginParameter, PluginOutput
from src.plugins.datasource import DataSource, OutputSource
from src.llm.client import get_llm_client


class LatexToPDFOutput(PluginOutput):
    file_id: str
    pdf_path: str
    attempts: int = 1


class LatexToPDFPlugin(Plugin):
    id = "latex_to_pdf"
    name = "Компиляция PDF"
    description = "Компилирует LaTeX-файл в PDF с автоисправлением ошибок"
    version = "1.0.0"
    category = "media"
    color = "#ef4444"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>'

    system_packages = [
        "texlive-latex-base",
        "texlive-fonts-recommended",
        "texlive-latex-extra",
        "texlive-lang-cyrillic"
    ]

    input_model = None
    output_model = LatexToPDFOutput

    data_sources = {
        "latex_file": DataSource(
            type="file",
            filename="document.tex",
            required=True,
        ),
    }

    output_artifacts = {
        "output": OutputSource(type="file", filename="document.pdf"),
    }

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
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> LatexToPDFOutput:
        max_attempts = parameters.get("max_attempts", 3)
        use_llm_repair = parameters.get("use_llm_repair", True)

        source = context.manifest.get("latex_file")
        if source is None:
            raise ValueError("data_source 'latex_file' не найден.")

        latex_path = Path(source.path)
        if not latex_path.exists():
            raise FileNotFoundError(f"LaTeX file not found: {latex_path}")

        context.report_progress(10, "Проверяем файл...")

        work_dir = tempfile.mkdtemp()
        work_latex = Path(work_dir) / "document.tex"

        try:
            shutil.copy2(str(latex_path), str(work_latex))

            attempts = 0
            success = False
            last_error = ""
            work_pdf = Path(work_dir) / "document.pdf"

            while attempts < max_attempts:
                attempts += 1
                context.report_progress(
                    20 + int(30 * (attempts - 1) / max_attempts),
                    f"Компиляция (попытка {attempts}/{max_attempts})..."
                )

                result = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-output-directory", work_dir, str(work_latex)],
                    capture_output=True,
                    text=False,
                    cwd=work_dir
                )
                stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
                stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

                if work_pdf.exists():
                    success = True
                    break

                last_error = stdout + stderr

                if use_llm_repair and attempts < max_attempts:
                    context.report_progress(
                        50,
                        f"Исправляем через LLM (попытка {attempts})..."
                    )
                    latex_content = self._repair_latex(work_latex.read_text(encoding="utf-8"), last_error, context)
                    work_latex.write_text(latex_content, encoding="utf-8")

            if not success:
                raise Exception(f"PDF compilation failed after {attempts} attempts: {last_error[:500]}")

            context.report_progress(90, "Сохраняем PDF...")

            output_artifact = context.output.declare("output", type="file")
            shutil.copy2(str(work_pdf), str(output_artifact.path))

            context.report_progress(100, "PDF готов!")

            return LatexToPDFOutput(
                file_id="",
                pdf_path=str(output_artifact.path),
                attempts=attempts,
            )

        finally:
            if work_dir and os.path.exists(work_dir):
                try:
                    shutil.rmtree(work_dir)
                except Exception:
                    pass

    def _repair_latex(self, latex_code: str, error_log: str, context: PluginContext) -> str:
        try:
            client = get_llm_client()

            repair_prompt = (
                "Ты — эксперт по верстке документов в LaTeX. "
                "Проанализируй лог ошибок компиляции и исправь LaTeX-код. "
                "Верни ТОЛЬКО исправленный код без комментариев и объяснений."
            )

            context_chunk = latex_code[:25000]
            error_chunk = error_log[:2000]
            llm_prompt = f"Лог ошибок:\n{error_chunk}\n\nКод:\n{context_chunk}"

            fixed_latex = client.completion(
                purpose="smart",
                messages=[
                    {"role": "system", "content": repair_prompt},
                    {"role": "user", "content": llm_prompt}
                ]
            )

            fixed_latex = fixed_latex.strip()

            if fixed_latex.startswith("```latex"):
                fixed_latex = fixed_latex[8:]
            if fixed_latex.startswith("```"):
                fixed_latex = fixed_latex[3:]
            if fixed_latex.endswith("```"):
                fixed_latex = fixed_latex[:-3]

            return fixed_latex.strip()

        except Exception as e:
            context.log("warning", f"LaTeX repair failed: {e}")
            return latex_code


plugin = LatexToPDFPlugin
