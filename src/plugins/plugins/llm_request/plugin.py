"""
LLM Request Plugin — makes requests to LLM API
"""

import json
import os
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginInput,
    PluginOutput,
    PluginParameter
)


class LLMRequestInput(BaseModel):
    """Input for LLM request plugin"""
    file_id: str
    prompt_id: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    variables: Dict[str, Any] = Field(default_factory=dict)


class LLMRequestOutput(BaseModel):
    """Output from LLM request plugin"""
    file_id: str
    response: str
    model: str = ""
    tokens_used: int = 0
    execution_time_ms: int = 0


class LLMRequestPlugin(Plugin):
    """Make requests to LLM API (DeepSeek, OpenAI, etc.)"""

    id = "llm_request"
    name = "LLM Запрос"
    description = "Выполняет запрос к LLM API с заданным промптом"
    version = "1.0.0"
    category = "ai"
    color = "#06b6d4"
    icon_svg = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>'

    input_model = LLMRequestInput
    output_model = LLMRequestOutput

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
        input_data: LLMRequestInput,
        context: PluginContext,
        parameters: Dict[str, Any]
    ) -> LLMRequestOutput:
        """Execute LLM request"""
        import time
        start_time = time.time()

        context.report_progress(10, "Подготовка промпта...")

        # Get prompt from library or inline
        system_prompt = input_data.system_prompt or ""
        user_prompt_template = input_data.user_prompt_template or ""

        if input_data.prompt_id and context.minio_client:
            context.report_progress(20, "Загрузка промпта из библиотеки...")
            # Load from MinIO
            prompt_data = self._load_prompt_from_minio(input_data.prompt_id, context)
            if prompt_data:
                system_prompt = prompt_data.get("system_prompt", system_prompt)
                user_prompt_template = prompt_data.get("user_prompt_template", user_prompt_template)

        # Render template with variables
        user_prompt = user_prompt_template
        for var_name, var_value in input_data.variables.items():
            placeholder = f"{{{{{var_name}}}}}"
            user_prompt = user_prompt.replace(placeholder, str(var_value))

        context.report_progress(30, f"Отправка запроса к {parameters.get('model', 'deepseek')}...")

        # Get LLM client
        model = parameters.get("model", "deepseek-chat")
        temperature = parameters.get("temperature", 0.7)
        max_tokens = parameters.get("max_tokens", 4096)

        # Make request
        try:
            from src.llm.client import get_llm_client
            client = get_llm_client()

            context.report_progress(50, "Ожидание ответа...")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )

            result_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if hasattr(response, 'usage') else 0

            execution_time_ms = int((time.time() - start_time) * 1000)

            context.report_progress(100, "Готово!")

            return LLMRequestOutput(
                file_id=input_data.file_id,
                response=result_text,
                model=model,
                tokens_used=tokens_used,
                execution_time_ms=execution_time_ms
            )

        except Exception as e:
            context.log("error", f"LLM request failed: {str(e)}")
            raise

    def _load_prompt_from_minio(self, prompt_id: str, context: PluginContext) -> Optional[dict]:
        """Load prompt from MinIO"""
        if not context.minio_client:
            return None

        try:
            key = f"prompts/{prompt_id}.json"
            response = context.minio_client.get_object(Bucket="lectify", Key=key)
            return json.loads(response["Body"].read())
        except Exception as e:
            context.log("warning", f"Failed to load prompt {prompt_id}: {e}")
            return None