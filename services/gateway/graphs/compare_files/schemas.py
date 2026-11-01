from pydantic import BaseModel, ConfigDict, Field

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    left_id: str = Field(min_length=1, max_length=128)
    right_id: str = Field(min_length=1, max_length=128)

class File(BaseModel):
    id: str
    filename: str

class Output(BaseModel):
    left: File
    right: File
    same_content: bool
