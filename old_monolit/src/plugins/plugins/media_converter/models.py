from src.plugins.base import PluginInput, PluginOutput


class MediaConverterInput(PluginInput):
    file_id: str


class MediaConverterOutput(PluginOutput):
    file_id: str
    format: str = "m4a"
    duration_ms: int
