from pydantic import BaseModel


class LatexToPDFInput(BaseModel):
    file_id: str
    latex_path: str


class LatexToPDFOutput(BaseModel):
    file_id: str
    pdf_path: str
