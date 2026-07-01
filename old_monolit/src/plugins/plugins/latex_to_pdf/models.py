from src.plugins.base import PluginInput, PluginOutput


class LatexToPDFInput(PluginInput):
    file_id: str


class LatexToPDFOutput(PluginOutput):
    file_id: str
    pdf_path: str
    attempts: int = 1
