from src.plugins.base import PluginInput, PluginOutput


class TextToMDInput(PluginInput):
    file_id: str
    prompt_id: str


class TextToMDOutput(PluginOutput):
    file_id: str
    char_count: int = 0
