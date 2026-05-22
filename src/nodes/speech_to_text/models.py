from pydantic import BaseModel


class SpeechToTextInput(BaseModel):
    file_id: str
    media_path: str


class SpeechToTextOutput(BaseModel):
    file_id: str
    txt_path: str
