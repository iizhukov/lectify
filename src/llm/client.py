from typing import Optional

from src.config import config
from src.llm.manager import LLMManager


_client: Optional[LLMManager] = None


def get_llm_client() -> LLMManager:
    global _client

    if _client is None:
        _client = LLMManager(
            api_key=config.openai_api_key,
            base_url=config.openai_api_url,
        )

    return _client
