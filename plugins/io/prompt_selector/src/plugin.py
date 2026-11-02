import json


class PluginHandler:
    def __init__(self, context, sidecar):
        self.context, self.sidecar = context, sidecar

    async def on_start(self):
        prompt_id = self.context.parameters.prompt_id
        if not isinstance(prompt_id,str) or not 1 <= len(prompt_id) <= 128:
            raise ValueError('A bounded prompt ID is required')
        prompt = await self.sidecar.fetch_prompt(prompt_id,raw_template=True)
        return {'prompt':json.dumps(prompt,ensure_ascii=False,allow_nan=False).encode('utf-8')}

    async def on_finish(self):
        pass
