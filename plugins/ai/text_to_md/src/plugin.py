import asyncio
import json
import math
import re

_VARIABLE = re.compile(r'\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}')
_STYLES = {'brief':'краткий','detailed':'подробный','academic':'академический'}


class PluginHandler:
    def __init__(self, context, sidecar):
        self.context,self.sidecar = context,sidecar
        self.buffers = {'text':bytearray(),'prompt':bytearray()}

    async def on_start(self):
        p = self.context.parameters
        if (type(p.max_chars) is not int or not 1<=p.max_chars<=65536 or p.style not in _STYLES
                or type(p.max_tokens) is not int or not 1<=p.max_tokens<=32768
                or type(p.timeout) is not int or not 1<=p.timeout<=300
                or isinstance(p.temperature,bool) or not isinstance(p.temperature,(int,float))
                or not math.isfinite(p.temperature) or not 0<=p.temperature<=2):
            raise ValueError('Invalid Markdown generation parameters')
        if not isinstance(p.values,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in p.values.items()):
            raise ValueError('Prompt variables must be strings')

    async def process_input(self, name, payload):
        if name not in self.buffers or len(self.buffers[name])+len(payload)>1048576:
            raise ValueError('Invalid or oversized Markdown input')
        self.buffers[name].extend(payload)

    def messages(self):
        p = self.context.parameters
        text = bytes(self.buffers['text']).decode('utf-8')[:p.max_chars]
        if not text.strip():
            raise ValueError('Text for Markdown generation is empty')
        if self.buffers['prompt']:
            prompt = json.loads(self.buffers['prompt'])
            system, user = prompt['system_prompt'], prompt['user_prompt_template']
        else:
            system = ('Ты — методист. Создай '+_STYLES[p.style]+' структурированный конспект в Markdown. '
                      'Используй заголовки, списки, выделение терминов и примеры. Пиши на языке исходного текста.')
            user = '{{transcript}}'
        if not isinstance(system,str) or not isinstance(user,str):
            raise ValueError('Invalid Markdown prompt')
        values = dict(p.values,transcript=text,text=text)
        if set(_VARIABLE.findall(system+'\n'+user))-values.keys():
            raise ValueError('Required prompt variable is missing')
        render = lambda template:_VARIABLE.sub(lambda match:values[match.group(1)],template)
        messages = [{'role':'system','content':render(system)},{'role':'user','content':render(user)}]
        if sum(len(m['content'].encode()) for m in messages)>1048576:
            raise ValueError('Rendered Markdown prompt exceeds limit')
        return messages

    async def on_finish(self):
        p = self.context.parameters
        parts,size = [],0
        async with asyncio.timeout(p.timeout):
            async for delta in self.sidecar.call_llm(model=p.model,messages=self.messages(),temperature=p.temperature,
                    max_tokens=p.max_tokens,purpose='summary'):
                size += len(delta.encode('utf-8'))
                if size>4194304: raise ValueError('Markdown result exceeds limit')
                parts.append(delta)
        content = ''.join(parts)
        if not content.strip(): raise ValueError('LLM returned an empty Markdown document')
        data = content.encode('utf-8')
        await self.sidecar.save_artifact(artifact_name='output',filename='output.md',content_type='text/markdown',data=data)
        return {'md_stream':data,'metadata':json.dumps({'char_count':len(content)}).encode()}
