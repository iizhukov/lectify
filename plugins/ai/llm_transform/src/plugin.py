from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from generated.models import PluginContext
    from generated.sidecar_client import SidecarAgentClient


class PluginHandler:
    def __init__(self, context: PluginContext, sidecar: SidecarAgentClient) -> None:
        self.context = context
        self.sidecar = sidecar
        self.transformed_paragraphs: List[str] = []
        self.paragraph_count = 0

    async def on_start(self) -> None:
        await self.sidecar.log("info", "Starting LLM Transform stream", model=self.context.parameters.model)
        await self.sidecar.report_progress(5, "LLM Transformer initialized")

    async def process_buffer(self, buffer: bytes) -> dict[str, bytes] | None:
        """
        Processes an accumulated paragraph of text.
        """
        if not buffer:
            return

        text = buffer.decode("utf-8").strip()
        if not text:
            return

        self.paragraph_count += 1
        await self.sidecar.report_progress(
            min(10 + self.paragraph_count * 10, 90),
            f"Transforming paragraph #{self.paragraph_count}...",
        )

        parts = []
        async for delta in self.sidecar.call_llm(
            model=self.context.parameters.model,
            messages=[
                {"role": "system", "content": self.context.parameters.prompt_template},
                {"role": "user", "content": text},
            ],
            temperature=self.context.parameters.temperature,
            purpose="transform",
        ):
            parts.append(delta)
        transformed = "".join(parts)
        if not transformed.strip():
            raise ValueError("LLM returned an empty transformation")
        self.transformed_paragraphs.append(transformed)
        return {"transformed_stream": transformed.encode("utf-8")}

    async def on_finish(self) -> None:
        if not self.transformed_paragraphs:
            raise ValueError("No transformed text to save")
        full_document = "\n\n".join(self.transformed_paragraphs)

        artifact_result = await self.sidecar.save_artifact(
            artifact_name="result_file",
            filename="result.md",
            content_type="text/markdown",
            data=full_document.encode("utf-8"),
        )

        await self.sidecar.log("info", "LLM Transform finished", artifact=artifact_result)
        await self.sidecar.report_progress(100, "Transformation complete")
