from typing import Any, Dict, Optional

from src.plugins.base import Plugin, PluginContext, PluginParameter
from src.plugins.plugins.prompt_selector.models import PromptSelectorOutput


class PromptSelectorPlugin(Plugin):
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

    input_model = None
    output_model = PromptSelectorOutput

    data_sources = {}

    parameters_schema = [
        PluginParameter(
            name="prompt_id",
            type="string",
            description="ID промпта из библиотеки",
            required=True,
            default="",
            options=[]
        ),
    ]

    async def execute(
        self,
        context: PluginContext,
        parameters: Dict[str, Any],
    ) -> PromptSelectorOutput:
        prompt_id = parameters.get("prompt_id", "")

        context.report_progress(20, f"Загрузка промпта: {prompt_id}")

        prompt_name = ""
        system_prompt = ""
        user_prompt_template = ""

        if prompt_id:
            extra = context.manifest.extra("prompt")
            prompt_name = extra.get("prompt_prompt_title", "")
            system_prompt = extra.get("prompt_system_prompt", "")
            user_prompt_template = extra.get("prompt_user_prompt_template", "")

            if not prompt_name:
                db_data = self._load_prompt_from_db(prompt_id)
                if db_data:
                    prompt_name = db_data.get("name", "")
                    system_prompt = db_data.get("system_prompt", "")
                    user_prompt_template = db_data.get("user_prompt_template", "")

        context.report_progress(100, f"Промпт «{prompt_name}» загружен")

        return PromptSelectorOutput(
            prompt_id=prompt_id,
            prompt_name=prompt_name,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            resolved_variables={},
        )

    def _load_prompt_from_db(self, prompt_id: str) -> Optional[dict]:
        """Load a prompt by ID from the database (local execution fallback)."""
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
        except Exception:
            pass
        return None


plugin = PromptSelectorPlugin
