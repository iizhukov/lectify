from src.plugins.base import PluginInput, PluginOutput


class SpeechToTextInput(PluginInput):
    file_id: str


class SpeechToTextOutput(PluginOutput):
    file_id: str
    txt_path: str
    duration_ms: int = 0
    language: str = "ru"
