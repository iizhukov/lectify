"""
Prompt Selector Plugin — picks a prompt from library and passes it forward

Acts as a prompt provider node. Takes a prompt_id as a parameter,
resolves it from the database, and outputs the rendered prompt text
for downstream nodes that need a prompt (e.g. LLM request).
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel

from src.plugins.base import (
    Plugin,
    PluginContext,
    PluginParameter,
)


class PromptSelectorInput(BaseModel):
    """Input is empty — this node doesn't consume upstream output."""
    pass


class PromptSelectorOutput(BaseModel):
    """Output: resolved prompt text + metadata."""
    prompt_id: str = ""
    prompt_name: str = ""
    system_prompt: str = ""
    user_prompt_template: str = ""
    resolved_variables: Dict[str, Any] = {}


class PromptSelectorPlugin(Plugin):
    """
    Select a prompt from the library and forward it downstream.

    Downstream nodes (e.g. llm_request) can reference the output fields:
      - $prompt_provider.output.system_prompt
      - $prompt_provider.output.user_prompt_template
    via input_mapping.
    """

    id = "prompt_selector"
    name = "Выбор промпта"
    description = "Выбирает промпт из библиотеки и передаёт его дальше по графу"
    version = "1.0.0"
    category = "io"
    color = "#3b82f6"
    icon_svg = (
        '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>'
        '</svg>'
    )

    input_model = PromptSelectorInput
    output_model = PromptSelectorOutput

    parameters_schema = [
        PluginParameter(
            name="prompt_id",
            type="string",
            description="ID промпта из библиотеки",
            required=True,
            default="",
            options=[]  # Frontend fetches options from /api/prompts
        ),
    ]

    async def execute(
        self,
        input_data: PromptSelectorInput,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> PromptSelectorOutput:
        """Resolve prompt from database and pass forward."""
        prompt_id = parameters.get("prompt_id", "")

        context.report_progress(20, f"Загрузка промпта: {prompt_id}")

        prompt_name = ""
        system_prompt = ""
        user_prompt_template = ""

        if prompt_id:
            prompt = self._load_prompt_from_db(prompt_id)
            if prompt:
                prompt_name = prompt.get("name", "")
                system_prompt = prompt.get("system_prompt", "")
                user_prompt_template = prompt.get("user_prompt_template", "")

        context.report_progress(100, f"Промпт «{prompt_name}» загружен")

        return PromptSelectorOutput(
            prompt_id=prompt_id,
            prompt_name=prompt_name,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            resolved_variables={},
        )

    def _load_prompt_from_db(self, prompt_id: str) -> Optional[dict]:
        """Load a prompt by ID from the database."""
        try:
            from src.db.database import SessionLocal
            from src.db.entity import DBPrompt
            session = SessionLocal()
            try:
                prompt = session.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()
                if prompt:
                    return {
                        "name": prompt.name,
                        "system_prompt": prompt.system_prompt or "",
                        "user_prompt_template": prompt.user_prompt_template or "",
                        "variables": prompt.variables or [],
                    }
            finally:
                session.close()
        except Exception as e:
            pass
        return None
