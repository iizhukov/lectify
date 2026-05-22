from pydantic import BaseModel


class TextToLatexInput(BaseModel):
    file_id: str
    txt_path: str


class TextToLatexOutput(BaseModel):
    file_id: str
    latex_path: str
