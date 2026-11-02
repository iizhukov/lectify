import asyncio
import json
import math
import re

_VARIABLE = re.compile(r'\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}')


class PluginHandler:
    def __init__(self, context, sidecar):
        self.context, self.sidecar = context, sidecar
        self.buffers = {'text':bytearray(),'prompt':bytearray()}

    async def on_start(self):
        p = self.context.parameters
        if (type(p.max_tokens) is not int or not 1<=p.max_tokens<=32768 or type(p.timeout) is not int
                or not 1<=p.timeout<=300 or isinstance(p.temperature,bool)
                or not isinstance(p.temperature,(int,float)) or not math.isfinite(p.temperature)
                or not 0<=p.temperature<=2):
            raise ValueError('Invalid LLM request limits')
        if not isinstance(p.values,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in p.values.items()):
            raise ValueError('Prompt variables must be strings')

    async def process_input(self, name, payload):
        if name not in self.buffers or len(self.buffers[name])+len(payload)>1048576:
            raise ValueError('Invalid or oversized LLM input')
        self.buffers[name].extend(payload)

    def messages(self):
        p = self.context.parameters
        text = bytes(self.buffers['text']).decode('utf-8')
        system, template = p.system_prompt, p.user_prompt_template
        if self.buffers['prompt']:
            prompt = json.loads(self.buffers['prompt'])
            system, template = prompt['system_prompt'], prompt['user_prompt_template']
        if not isinstance(system,str) or not isinstance(template,str):
            raise ValueError('Invalid prompt template')
        values = dict(p.values)
        for key in ('text','transcript'):
            values.setdefault(key,text)
        names = set(_VARIABLE.findall(system+'\n'+template))
        if names-values.keys():
            raise ValueError('Required prompt variable is missing')
        render = lambda source:_VARIABLE.sub(lambda match:values[match.group(1)],source)
        messages = [{'role':'system','content':render(system)},{'role':'user','content':render(template)}]
        if sum(len(m['content'].encode()) for m in messages)>1048576:
            raise ValueError('Rendered prompt exceeds limit')
        return messages

    async def on_finish(self):
        p = self.context.parameters
        parts, size = [], 0
        async with asyncio.timeout(p.timeout):
            async for delta in self.sidecar.call_llm(model=p.model,messages=self.messages(),
                    temperature=p.temperature,max_tokens=p.max_tokens,purpose='llm_request'):
                size += len(delta.encode('utf-8'))
                if size>4194304:
                    raise ValueError('LLM result exceeds limit')
                parts.append(delta)
        result = ''.join(parts)
        if not result.strip():
            raise ValueError('LLM returned an empty result')
        await self.sidecar.save_artifact(artifact_name='result_file',filename='response.txt',
            content_type='text/plain',data=result.encode('utf-8'))
        return {'response':result.encode('utf-8')}
