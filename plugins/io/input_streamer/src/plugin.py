from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from generated.models import PluginContext
    from generated.sidecar_client import SidecarAgentClient


class PluginHandler:
    def __init__(self, context: PluginContext, sidecar: SidecarAgentClient) -> None:
        self.context = context
        self.sidecar = sidecar

    async def on_start(self) -> None:
        parameters = self.context.parameters
        if not parameters.file_id.strip() or len(parameters.file_id) > 128:
            raise ValueError('A valid source file id is required')
        size = parameters.chunk_size_bytes
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 1048576:
            raise ValueError('Source chunk size must be between 1 and 1048576 bytes')

    async def produce(self):
        async for chunk in self.sidecar.read_file(
            file_id=self.context.parameters.file_id,
            chunk_size_bytes=self.context.parameters.chunk_size_bytes,
        ):
            if chunk:
                yield {'data_stream': chunk}

    async def on_finish(self) -> None:
        pass
