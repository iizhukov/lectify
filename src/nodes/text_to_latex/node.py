import sys
import pathlib
import subprocess

from src.nodes.basenode import BaseNode
from src.nodes.text_to_latex.models import TextToLatexInput, TextToLatexOutput
from src.db.models import NodeStatus
from src.prompts.registry import get_prompt


class TextToLatexNode(BaseNode):
    def __init__(self):
        super().__init__(
            node_id="text_to_latex",
            name="Создание LaTeX-конспекта",
            input_model=TextToLatexInput,
            output_model=TextToLatexOutput
        )

    def run(self, input_data: TextToLatexInput, client) -> TextToLatexOutput:
        file_id = input_data.file_id
        txt_path = input_data.txt_path

        self.update_status(file_id, NodeStatus.RUNNING, "Создание LaTeX-конспекта...")
        try:
            txt_file = pathlib.Path(txt_path)
            if not txt_file.exists():
                raise FileNotFoundError(f"Файл распознанного текста {txt_path} не найден")

            with open(str(txt_file), 'r', encoding='utf-8') as f:
                text = f.read()
            first_100 = ' '.join(text.split()[:100])

            prompt_for_sys = get_prompt("latex_classifier_system")
            
            subject = client.completion(
                purpose="smart",
                messages=[
                    {"role": "system", "content": prompt_for_sys},
                    {"role": "user", "content": first_100},
                ]
            ).strip()

            valid = ['chemistry', 'history', 'math', 'physics', 'sociology', 'sys_prompt']
            if subject not in valid:
                subject = 'sys_prompt'
                
            res = subprocess.run(
                [
                    sys.executable, "text_to_latex.py",
                    "--file", str(txt_file),
                    "--seg-num", "3",
                    "--sys-prompt", f"resources/prompts/{subject}.txt",
                    "--language", "ru-RU"
                ],
                capture_output=True, text=True
            )
            if res.returncode != 0:
                raise Exception(f"Скрипт text_to_latex.py завершился с ошибкой: {res.stderr or res.stdout}")

            latex_path = str(txt_file.with_suffix(".tex"))
            if pathlib.Path(latex_path).exists():
                self.update_status(file_id, NodeStatus.COMPLETED, "LaTeX-конспект успешно создан!", latex_path)

                return TextToLatexOutput(file_id=file_id, latex_path=latex_path)

            raise Exception("LaTeX-файл не был создан скриптом text_to_latex.py")
        except Exception as e:
            self.update_status(file_id, NodeStatus.FAILED, f"Ошибка: {str(e)}")
            raise e
