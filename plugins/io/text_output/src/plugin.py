class PluginHandler:
    def __init__(self, context, sidecar):
        self.context, self.sidecar = context, sidecar
        self.parts = []

    async def on_start(self):
        filename = self.context.parameters.filename
        if not filename or len(filename) > 128 or any(c in filename for c in '/\\\x00\r\n'):
            raise ValueError('Invalid output filename')

    async def process_buffer(self, buffer):
        buffer.decode('utf-8')
        self.parts.append(buffer)

    async def on_finish(self):
        await self.sidecar.save_artifact(artifact_name='result', filename=self.context.parameters.filename,
            content_type='text/plain', data=b''.join(self.parts))
