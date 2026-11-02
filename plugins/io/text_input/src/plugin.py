class PluginHandler:
    def __init__(self, context, sidecar):
        pass

    async def on_start(self):
        pass

    async def process_buffer(self, buffer):
        buffer.decode('utf-8')
        return {'text': buffer}

    async def on_finish(self):
        pass
