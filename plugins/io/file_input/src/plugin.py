class PluginHandler:
    def __init__(self, context, sidecar):
        self.sidecar = sidecar
        self.file_id = None

    async def on_start(self):
        pass

    async def process_buffer(self, buffer):
        if self.file_id is not None:
            raise ValueError('Exactly one file ID is required')
        value = buffer.decode('utf-8')
        if not value or len(value) > 128 or value.strip() != value:
            raise ValueError('Invalid file ID')
        self.file_id = value
        async def outputs():
            async for chunk in self.sidecar.read_file(file_id=value, chunk_size_bytes=65536):
                if chunk:
                    yield {'data': chunk}
        return outputs()

    async def on_finish(self):
        if self.file_id is None:
            raise ValueError('File ID is missing')
