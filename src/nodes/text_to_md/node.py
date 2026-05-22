import pathlib

from src.nodes.basenode import BaseNode
from src.nodes.text_to_md.models import TextToMDInput, TextToMDOutput
from src.db.models import NodeStatus
from src.prompts.registry import get_prompt


class TextToMDNode(BaseNode):
    def __init__(self):
        super().__init__(
            node_id="text_to_md",
            name="Создание Markdown-конспекта",
            input_model=TextToMDInput,
            output_model=TextToMDOutput
        )

    def run(self, input_data: TextToMDInput, client) -> TextToMDOutput:
        file_id = input_data.file_id
        txt_path = input_data.txt_path

        self.update_status(file_id, NodeStatus.RUNNING, "Создание Markdown-конспекта...")
        try:
            txt_file = pathlib.Path(txt_path)
            if not txt_file.exists():
                raise FileNotFoundError(f"Файл распознанного текста {txt_path} не найден")

            with open(str(txt_file), "r", encoding="utf-8") as f:
                text = f.read()
                
            prompt = get_prompt("text_to_md_system")
            
            content = client.completion(
                purpose="medium",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text[:40000]}
                ]
            )
            
            md_path = str(txt_file.with_suffix(".md"))
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content)
                
            self.update_status(file_id, NodeStatus.COMPLETED, "Markdown-конспект успешно создан!", md_path)
            return TextToMDOutput(file_id=file_id, md_path=md_path)
        except Exception as e:
            self.update_status(file_id, NodeStatus.FAILED, f"Ошибка: {str(e)}")
            raise e
