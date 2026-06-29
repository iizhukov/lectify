import time as time_module

from openai import OpenAI
from openai import APIError as OpenAI_APIError, RateLimitError, APITimeoutError

from src.utils.metrics import get_metrics


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
    ):
        self.api_key = api_key
        self.base_url = base_url

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        self.models = MODELS

    def get_client(self) -> OpenAI:
        return self.client

    def get_model_name(self, purpose: str) -> str:
        return self.models.get(purpose, self.models["medium"])

    def completion(self, purpose: str, messages: list, **kwargs) -> str:
        metrics = get_metrics()
        start = time_module.time()
        status = "success"

        try:
            model = self.get_model_name(purpose)
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
            return response.choices[0].message.content
        except RateLimitError:
            status = "rate_limited"
            raise
        except APITimeoutError:
            status = "timeout"
            raise
        except OpenAI_APIError as e:
            status = f"api_error_{getattr(e, 'status_code', None) or 'unknown'}"
            raise
        except Exception:
            status = "unknown_error"
            raise
        finally:
            duration = time_module.time() - start
            metrics.llm_api_requests.labels(purpose=purpose, status=status).inc()
            metrics.llm_api_duration.labels(purpose=purpose).observe(duration)

            if status != "success":
                metrics.llm_api_errors.labels(purpose=purpose, error_type=status).inc()
