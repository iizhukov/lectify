from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from generated.models import PluginContext
    from generated.sidecar_client import SidecarAgentClient


class PluginHandler:
    def __init__(self, context: PluginContext, sidecar: SidecarAgentClient) -> None:
        self.context = context
        self.sidecar = sidecar
        self._lines: list[str] = []

    async def on_start(self) -> dict[str, bytes]:
        title = self.context.parameters.title
        if not title.strip() or '\n' in title or '\r' in title:
            raise ValueError('Document title must be a nonempty single line')
        return {'md_stream': ('# ' + title + '\n\n').encode('utf-8')}

    async def process_buffer(self, buffer: bytes) -> dict[str, bytes] | None:
        text = buffer.decode('utf-8')
        self._lines.append(text)
        return {'md_stream': (text + '\n').encode('utf-8')}

    async def on_finish(self) -> None:
        if not any(line.strip() for line in self._lines):
            raise ValueError('No text to format')
        document = '# ' + self.context.parameters.title + '\n\n' + '\n'.join(self._lines) + '\n'
        await self.sidecar.save_artifact(
            artifact_name='md_file', filename='notes.md', content_type='text/markdown',
            data=document.encode('utf-8'),
        )
