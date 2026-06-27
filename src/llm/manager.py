from openai import OpenAI

from src.utils.metrics import metrics


MODELS = {
    "smart": "deepseek/deepseek-r1",
    "medium": "openai/gpt-4o",
    "stt": "openai/whisper-1",
    "tts": "openai/tts-1"
}


class LLMManager:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        self.models = MODELS

    def get_client(self) -> OpenAI:
        """Возвращает инициализированный клиент OpenAI"""
        return self.client

    def get_model_name(self, purpose: str) -> str:
        """Возвращает ID модели под конкретное назначение"""
        return self.models.get(purpose, self.models["medium"])

    def completion(self, purpose: str, messages: list, **kwargs) -> str:
        """Вспомогательный метод для быстрых текстовых запросов"""
        import time
        model = self.get_model_name(purpose)
        start = time.time()
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
            duration = time.time() - start
            metrics.llm_api_requests.labels(purpose=purpose, status="success").inc()
            metrics.llm_api_duration.labels(purpose=purpose).observe(duration)
            return response.choices[0].message.content
        except Exception:
            metrics.llm_api_requests.labels(purpose=purpose, status="error").inc()
            metrics.llm_api_errors.labels(purpose=purpose, error_type="request_failed").inc()
            raise
