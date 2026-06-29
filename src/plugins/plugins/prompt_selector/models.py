from typing import Dict, Any

from src.plugins.base import PluginOutput


class PromptSelectorOutput(PluginOutput):
    """Output: resolved prompt text + metadata."""
    prompt_id: str = ""
    prompt_name: str = ""
    system_prompt: str = ""
    user_prompt_template: str = ""
    resolved_variables: Dict[str, Any] = {}
