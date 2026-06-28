from src.plugins.base import PluginInput, PluginOutput


class InputPluginInput(PluginInput):
    file_id: str


class InputPluginOutput(PluginOutput):
    file_id: str
    input_type: str  # audio, video, pdf, text, image, any
