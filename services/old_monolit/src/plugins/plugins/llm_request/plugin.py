"""
LLM Request Plugin — makes requests to LLM API
"""

import time
from typing import Any, Dict

from src.plugins.base import Plugin, PluginContext, PluginParameter
from src.plugins.plugins.llm_request.models import LLMRequestInput, LLMRequestOutput
from src.llm.client import get_llm_client


class LLMRequestPlugin(Plugin):
    id = "llm_request"
    name = "LLM Запрос"
    description = "Выполняет запрос к LLM API с заданным промптом"
    version = "1.0.0"
    category = "ai"
    color = "#06b6d4"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>'

    input_model = LLMRequestInput
    output_model = LLMRequestOutput

    data_sources = {}

    parameters_schema = [
        PluginParameter(
            name="model",
            type="string",
            description="Модель LLM",
            required=True,
            default="deepseek-chat",
            options=["deepseek-chat", "gpt-4o", "gpt-4o-mini"]
        ),
        PluginParameter(
            name="temperature",
            type="float",
            description="Температура генерации",
            required=False,
            default=0.7,
            min_value=0.0,
            max_value=2.0
        ),
        PluginParameter(
            name="max_tokens",
            type="int",
            description="Максимум токенов",
            required=False,
            default=4096
        ),
        PluginParameter(
            name="timeout",
            type="int",
            description="Таймаут (сек)",
            required=False,
            default=120
        )
    ]

    async def execute(
        self,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> LLMRequestOutput:
        start_time = time.time()

        model = parameters.get("model", "deepseek-chat")
        temperature = parameters.get("temperature", 0.7)
        max_tokens = parameters.get("max_tokens", 4096)

        extra = context.manifest.extra("prompt")
        system_prompt = extra.get("prompt_system_prompt", "")
        user_prompt_template = extra.get("prompt_user_prompt_template", "")

        if not user_prompt_template:
            context.report_progress(10, "Подготовка промпта...")
            user_prompt_template = "Вставьте переменные через {variable_name} и передайте values в параметрах узла."

        context.report_progress(20, f"Отправка запроса к {model}...")

        client = get_llm_client()

        context.report_progress(50, "Ожидание ответа...")

        response = client.completion(
            purpose="llm_request",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt_template}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )

        result_text = response

        execution_time_ms = int((time.time() - start_time) * 1000)

        context.report_progress(100, "Готово!")

        return LLMRequestOutput(
            file_id="",
            response=result_text,
            model=model,
            tokens_used=0,
            execution_time_ms=execution_time_ms,
        )


plugin = LLMRequestPlugin
