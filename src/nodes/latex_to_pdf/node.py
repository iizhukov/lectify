import sys
import pathlib
import subprocess

from src.nodes.basenode import BaseNode
from src.nodes.latex_to_pdf.models import LatexToPDFInput, LatexToPDFOutput
from src.db.models import NodeStatus
from src.prompts.registry import get_prompt


class LatexToPDFNode(BaseNode):
    def __init__(self):
        super().__init__(
            node_id="latex_to_pdf",
            name="Компиляция PDF из LaTeX",
            input_model=LatexToPDFInput,
            output_model=LatexToPDFOutput
        )

    def run(self, input_data: LatexToPDFInput, client) -> LatexToPDFOutput:
        file_id = input_data.file_id
        latex_path = input_data.latex_path

        self.update_status(file_id, NodeStatus.RUNNING, "Компиляция PDF из LaTeX...")
        try:
            latex_file = pathlib.Path(latex_path)
            if not latex_file.exists():
                raise FileNotFoundError(f"LaTeX-файл {latex_path} не найден")

            res = subprocess.run(
                [
                    sys.executable, "latex_to_pdf.py",
                    "--file", str(latex_file),
                    "--clean"
                ],
                capture_output=True, text=True
            )

            attempts = 0
            max_attempts = 3
            
            while res.returncode != 0 and attempts < max_attempts:
                attempts += 1
                self.update_status(
                    file_id, 
                    NodeStatus.RUNNING, 
                    f"Компиляция не удалась. Попытка автоматического исправления LaTeX ошибок через LLM ({attempts} из {max_attempts})..."
                )
                
                error_log = res.stderr or res.stdout or "Неизвестная ошибка компиляции"
                
                with open(str(latex_file), "r", encoding="utf-8") as f:
                    latex_code = f.read()

                repair_prompt = get_prompt("latex_repair_system")

                context_chunk = latex_code[:25000]
                llm_prompt = f"Лог ошибок компиляции:\n{error_log}\n\nИсходный LaTeX-код лекции:\n{context_chunk}"
                
                fixed_latex = client.completion(
                    purpose="smart",
                    messages=[
                        {"role": "system", "content": repair_prompt},
                        {"role": "user", "content": llm_prompt}
                    ]
                )

                if "NEED_MORE_CONTEXT" in fixed_latex or len(latex_code) > 25000:
                    self.update_status(file_id, NodeStatus.RUNNING, f"Досылка дополнительного контекста лекции в LLM (попытка {attempts})...")

                    extended_chunk = latex_code[25000:50000]
                    llm_prompt_extended = (
                        f"Лог ошибок:\n{error_log}\n\n"
                        f"Первая часть кода:\n{context_chunk}\n\n"
                        f"Вторая часть кода лекции:\n{extended_chunk}"
                    )

                    fixed_latex = client.completion(
                        purpose="smart",
                        messages=[
                            {"role": "system", "content": repair_prompt},
                            {"role": "user", "content": llm_prompt_extended}
                        ]
                    )

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

                self.update_status(file_id, NodeStatus.RUNNING, f"Повторная компиляция исправленного LaTeX-файла (попытка {attempts})...")
                
                res = subprocess.run(
                    [
                        sys.executable, "latex_to_pdf.py",
                        "--file", str(latex_file),
                        "--clean"
                    ],
                    capture_output=True, text=True
                )

            if res.returncode != 0:
                raise Exception(f"Компиляция не удалась после {attempts} попыток автоисправления ИИ. Последняя ошибка: {res.stderr or res.stdout}")

            pdf_path = str(latex_file.with_suffix(".pdf"))
            if pathlib.Path(pdf_path).exists():
                msg = "PDF-файл успешно сгенерирован!"

                if attempts > 0:
                    msg = f"PDF-файл успешно сгенерирован (исправлен ИИ со {attempts} попытки)!"

                self.update_status(file_id, NodeStatus.COMPLETED, msg, pdf_path)

                return LatexToPDFOutput(file_id=file_id, pdf_path=pdf_path)

            raise Exception("PDF-файл не был создан скриптом latex_to_pdf.py")
        except Exception as e:
            self.update_status(file_id, NodeStatus.FAILED, f"Ошибка компиляции PDF: {str(e)}")
            raise e
