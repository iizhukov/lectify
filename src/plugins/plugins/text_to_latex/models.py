from src.plugins.base import PluginInput, PluginOutput


class TextToLatexInput(PluginInput):
    file_id: str
    prompt_id: str


class TextToLatexOutput(PluginOutput):
    file_id: str
    latex_path: str
