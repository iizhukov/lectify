"""
LaTeX to PDF Plugin — compile LaTeX to PDF
"""

import os
import pathlib
import subprocess
import tempfile
from typing import Any, Dict

from pydantic import BaseModel

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginParameter
)


class LatexToPDFInput(BaseModel):
    """Input for LaTeX-to-PDF plugin"""
    file_id: str = ""
    latex_path: str


class LatexToPDFOutput(BaseModel):
    """Output from LaTeX-to-PDF plugin"""
    file_id: str
    pdf_path: str
    attempts: int = 1


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
            suffix = pathlib.Path(object_name).suffix or ".tex"
            temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
            os.close(temp_fd)
            with open(temp_path, "wb") as f:
                f.write(bytes_data)
            return temp_path
        last_error = f"Object not found in MinIO (attempt {attempt + 1}/{max_retries}): {object_name}"
        if attempt < max_retries - 1:
            _time.sleep(0.5 * (2 ** attempt))
    raise FileNotFoundError(last_error)


class LatexToPDFPlugin(Plugin):
    """Compile LaTeX file to PDF"""

    id = "latex_to_pdf"
    name = "Компиляция PDF"
    description = "Компилирует LaTeX-файл в PDF с автоисправлением ошибок"
    version = "1.0.0"
    category = "media"
    color = "#ef4444"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>'

    # LaTeX packages required for PDF compilation
    system_packages = [
        "texlive-latex-base",
        "texlive-fonts-recommended",
        "texlive-latex-extra",
        "texlive-lang-cyrillic"
    ]

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
        latex_path_input = input_data.latex_path
        max_attempts = parameters.get("max_attempts", 3)
        use_llm_repair = parameters.get("use_llm_repair", True)

        context.report_progress(10, "Проверяем файл...")

        latex_path = ""
        is_temp = False
        work_dir = None
        try:
            # Handle minio:// URLs — download to temp file inside Docker
            if latex_path_input.startswith("minio://"):
                latex_path = _download_minio_to_temp(latex_path_input)
                is_temp = True
            else:
                latex_path = latex_path_input

            latex_file = pathlib.Path(latex_path)
            if not latex_file.exists():
                raise FileNotFoundError(f"LaTeX file not found: {latex_path}")

            # Create working directory for compilation
            work_dir = tempfile.mkdtemp()
            work_latex = pathlib.Path(work_dir) / "document.tex"

            # Copy LaTeX content to working directory
            with open(str(latex_file), "r", encoding="utf-8") as f:
                latex_content = f.read()

            with open(str(work_latex), "w", encoding="utf-8") as f:
                f.write(latex_content)

            attempts = 0
            success = False
            last_error = ""
            work_pdf = pathlib.Path(work_dir) / "document.pdf"

            while attempts < max_attempts:
                attempts += 1
                context.report_progress(
                    20 + int(30 * (attempts - 1) / max_attempts),
                    f"Компиляция (попытка {attempts}/{max_attempts})..."
                )

                # Run pdflatex
                result = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-output-directory", work_dir, str(work_latex)],
                    capture_output=True,
                    text=True,
                    cwd=work_dir
                )

                if work_pdf.exists():
                    success = True
                    break

                last_error = result.stdout + result.stderr

                # Compilation failed, try LLM repair
                if use_llm_repair and attempts < max_attempts:
                    context.report_progress(
                        50,
                        f"Исправляем через LLM (попытка {attempts})..."
                    )
                    latex_content = self._repair_latex(latex_content, last_error, context)
                    with open(str(work_latex), "w", encoding="utf-8") as f:
                        f.write(latex_content)

            if not success:
                raise Exception(f"PDF compilation failed after {attempts} attempts: {last_error[:500]}")

            # Determine output path
            if latex_path_input.startswith("minio://") or latex_path.startswith("/input/"):
                base_name = pathlib.Path(latex_path).stem if not latex_path_input.startswith("minio://") else "result"
                pdf_path = f"/output/{base_name}.pdf"
            else:
                pdf_path = str(latex_file.with_suffix(".pdf"))

            # Copy PDF to output location
            import shutil
            shutil.copy2(str(work_pdf), pdf_path)

            context.report_progress(100, "PDF готов!")

            return LatexToPDFOutput(
                file_id=file_id,
                pdf_path=pdf_path,
                attempts=attempts
            )

        except Exception as e:
            context.log("error", f"LaTeX-to-PDF failed: {str(e)}")
            raise
        finally:
            # Cleanup temp file from MinIO download
            if is_temp and os.path.exists(latex_path):
                try:
                    os.remove(latex_path)
                except Exception:
                    pass
            # Cleanup working directory
            if work_dir and os.path.exists(work_dir):
                try:
                    import shutil
                    shutil.rmtree(work_dir)
                except Exception:
                    pass

    def _repair_latex(self, latex_code: str, error_log: str, context: PluginContext) -> str:
        """Repair LaTeX using LLM and return fixed content"""
        try:
            from src.llm.client import get_llm_client
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

            # Clean markdown code blocks
            fixed_latex = fixed_latex.strip()
            if fixed_latex.startswith("```latex"):
                fixed_latex = fixed_latex[8:]
            if fixed_latex.startswith("```"):
                fixed_latex = fixed_latex[3:]
            if fixed_latex.endswith("```"):
                fixed_latex = fixed_latex[:-3]
            fixed_latex = fixed_latex.strip()

            return fixed_latex

        except Exception as e:
            context.log("warning", f"LaTeX repair failed: {e}")
            return latex_code
