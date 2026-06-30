from src.plugins.base import PluginOutput


class InputPluginOutput(PluginOutput):
    file_id: str
    input_type: str  # audio, video, pdf, text, image, any
