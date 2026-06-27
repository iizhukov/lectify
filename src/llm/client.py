import os
from typing import Optional

from src.config import config
from src.llm.manager import LLMManager


_client: Optional[LLMManager] = None


def get_llm_client() -> LLMManager:
    """
    Returns a singleton LLMManager instance configured from config.cfg.
    Called by all LLM-using plugins inside Docker containers.

    In plugin containers, detects plugin_id and execution_id from environment
    to enable Pushgateway metrics.
    """
    global _client

    if _client is None:
        # Detect if running in plugin container
        plugin_id = os.getenv("PLUGIN_ID")
        execution_id = os.getenv("EXECUTION_ID")

        _client = LLMManager(
            api_key=config.openai_api_key,
            base_url=config.openai_api_url,
            plugin_id=plugin_id,
            execution_id=execution_id,
        )

    return _client
