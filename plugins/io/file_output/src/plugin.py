class PluginHandler:
    def __init__(self, context, sidecar):
        self.context, self.sidecar = context, sidecar
        self.parts = []

    async def on_start(self):
        name = self.context.parameters.filename
        if not name or len(name)>128 or name in ('.','..') or any(ord(c)<32 or c in '/\\' for c in name):
            raise ValueError('Invalid output filename')

    async def process_buffer(self, buffer):
        self.parts.append(buffer)

    async def on_finish(self):
        await self.sidecar.save_artifact(artifact_name='result',filename=self.context.parameters.filename,
            content_type='application/octet-stream',data=b''.join(self.parts))
