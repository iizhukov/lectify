import os
from typing import Optional
from openai import OpenAI

from src.utils.metrics import metrics


MODELS = {
    "smart": "deepseek/deepseek-r1",
    "medium": "openai/gpt-4o",
    "stt": "openai/whisper-1",
    "tts": "openai/tts-1"
}


class LLMManager:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        plugin_id: Optional[str] = None,
        execution_id: Optional[str] = None
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.plugin_id = plugin_id
        self.execution_id = execution_id

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        self.models = MODELS

        # Use Pushgateway in plugin containers, regular metrics in main app
        self._in_container = os.getenv("PLUGIN_INPUT") is not None
        self._pushgateway_metrics = None

        if self._in_container and plugin_id and execution_id:
            try:
                from src.utils.pushgateway import get_pushgateway_metrics
                self._pushgateway_metrics = get_pushgateway_metrics(plugin_id, execution_id)
            except ImportError:
                pass  # Pushgateway not available

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

            # Record metrics
            if self._pushgateway_metrics:
                # In plugin container - push to Pushgateway
                self._pushgateway_metrics.llm_request(purpose, duration, status="success")
                self._pushgateway_metrics.push()
            else:
                # In main app - use regular Prometheus metrics
                metrics.llm_api_requests.labels(purpose=purpose, status="success").inc()
                metrics.llm_api_duration.labels(purpose=purpose).observe(duration)

            return response.choices[0].message.content
        except Exception as e:
            duration = time.time() - start

            # Record error metrics
            if self._pushgateway_metrics:
                self._pushgateway_metrics.llm_request(
                    purpose, duration, status="error", error_type="request_failed"
                )
                self._pushgateway_metrics.push()
            else:
                metrics.llm_api_requests.labels(purpose=purpose, status="error").inc()
                metrics.llm_api_errors.labels(purpose=purpose, error_type="request_failed").inc()

            raise
