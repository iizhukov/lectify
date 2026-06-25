from openai import OpenAI


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
        model = self.get_model_name(purpose)
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )

        return response.choices[0].message.content
