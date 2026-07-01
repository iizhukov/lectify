from src.plugins.base import PluginInput, PluginOutput


class LLMRequestInput(PluginInput):
    file_id: str


class LLMRequestOutput(PluginOutput):
    file_id: str
    response: str
    model: str = ""
    tokens_used: int = 0
    execution_time_ms: int = 0
