from pydantic import BaseModel


class TextToMDInput(BaseModel):
    file_id: str
    txt_path: str


class TextToMDOutput(BaseModel):
    file_id: str
    md_path: str
