from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from generated.models import PluginContext
    from generated.sidecar_client import SidecarAgentClient


class PluginHandler:
    def __init__(self, context: PluginContext, sidecar: SidecarAgentClient) -> None:
        self.context = context
        self.sidecar = sidecar
        self.transcripts: List[str] = []
        self.chunk_count = 0

    async def on_start(self) -> None:
        await self.sidecar.log("info", "Starting speech_to_text streaming transcription", model=self.context.parameters.model)
        await self.sidecar.report_progress(5, "Speech to text initialized")

    async def process_buffer(self, buffer: bytes) -> dict[str, bytes] | None:
        """
        Processes an accumulated buffer window (audio chunk).
        """
        if not buffer:
            return

        self.chunk_count += 1
        await self.sidecar.report_progress(
            min(10 + self.chunk_count * 15, 90),
            f"Transcribing audio chunk #{self.chunk_count} ({len(buffer)} bytes)...",
        )

        chunk_text = await self.sidecar.transcribe(
            buffer, model=self.context.parameters.model, language=self.context.parameters.language,
        )
        chunk_text = chunk_text.strip()
        if not chunk_text:
            return None
        payload = (" " if self.transcripts else "") + chunk_text
        self.transcripts.append(chunk_text)

        await self.sidecar.log("info", f"Transcribed chunk #{self.chunk_count}", length_bytes=len(buffer))
        return {"transcript_stream": payload.encode("utf-8")}

    async def on_finish(self) -> None:
        if not self.transcripts:
            raise ValueError("No speech transcript to save")
        full_transcript = " ".join(self.transcripts)

        # Upload final artifact to Lectify storage through sidecar
        artifact_result = await self.sidecar.save_artifact(
            artifact_name="transcript_file",
            filename="transcript.txt",
            content_type="text/plain",
            data=full_transcript.encode("utf-8"),
        )

        await self.sidecar.log(
            "info",
            "Speech to text completed",
            total_chunks=self.chunk_count,
            artifact=artifact_result,
        )
        await self.sidecar.report_progress(100, "Transcription completed successfully")
