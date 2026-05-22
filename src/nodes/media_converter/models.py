from pydantic import BaseModel


class MediaConverterInput(BaseModel):
    file_id: str
    file_path: str


class MediaConverterOutput(BaseModel):
    file_id: str
    media_path: str
