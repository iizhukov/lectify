import asyncio
import json
import re

_SUBJECTS = {'chemistry','history','math','physics','sociology','sys_prompt'}
_VARIABLE = re.compile(r'\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}')


def strip_fence(text):
    match=re.fullmatch(r'```(?:latex|tex)?\s*\n?(.*?)\n?```',text.strip(),re.S)
    return (match.group(1) if match else text).strip()


class PluginHandler:
    def __init__(self, context, sidecar):
        self.context,self.sidecar = context,sidecar
        self.buffers={'text':bytearray(),'prompt':bytearray()}

    async def on_start(self):
        p=self.context.parameters
        if (p.subject not in _SUBJECTS|{'auto'} or type(p.segments) is not int or not 1<=p.segments<=32
                or type(p.max_tokens) is not int or not 1<=p.max_tokens<=32768
                or type(p.timeout) is not int or not 1<=p.timeout<=300):
            raise ValueError('Invalid LaTeX generation parameters')
        if not isinstance(p.values,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in p.values.items()):
            raise ValueError('Prompt variables must be strings')

    async def process_input(self, name, payload):
        if name not in self.buffers or len(self.buffers[name])+len(payload)>1048576:
            raise ValueError('Invalid or oversized LaTeX generation input')
        self.buffers[name].extend(payload)

    async def completion(self, purpose, messages, max_tokens):
        result=[]; size=0
        async for delta in self.sidecar.call_llm(model=self.context.parameters.model,messages=messages,
                temperature=0,max_tokens=max_tokens,purpose=purpose):
            size+=len(delta.encode())
            if size>4194304: raise ValueError('LaTeX result exceeds limit')
            result.append(delta)
        return ''.join(result)

    async def on_finish(self):
        p=self.context.parameters
        text=bytes(self.buffers['text']).decode('utf-8')
        if not text.strip(): raise ValueError('Text for LaTeX generation is empty')
        async with asyncio.timeout(p.timeout):
            subject=p.subject
            if subject=='auto':
                classifier=[{'role':'system','content':'Return only one subject: chemistry, history, math, physics, sociology, sys_prompt.'},
                            {'role':'user','content':' '.join(text.split()[:100])[:8192]}]
                try: subject=(await self.completion('subject',classifier,32)).strip().lower()
                except Exception: subject='sys_prompt'
                if subject not in _SUBJECTS: subject='sys_prompt'
            if self.buffers['prompt']:
                prompt=json.loads(self.buffers['prompt'])
                system,user=prompt['system_prompt'],prompt['user_prompt_template']
            else:
                system=('Создай полный компилируемый LaTeX-конспект. Используй documentclass article, '
                        'inputenc utf8, fontenc T2A и babel russian для русского текста. '
                        'Добавь разделы, списки и математические окружения. Предмет: {{subject}}.')
                user='{{transcript}}'
            if not isinstance(system,str) or not isinstance(user,str): raise ValueError('Invalid LaTeX prompt')
            values=dict(p.values,text=text,transcript=text,subject=subject)
            if set(_VARIABLE.findall(system+'\n'+user))-values.keys(): raise ValueError('Required prompt variable is missing')
            render=lambda value:_VARIABLE.sub(lambda match:values[match.group(1)],value)
            messages=[{'role':'system','content':render(system)+f'\nРаздели материал на {p.segments} смысловых разделов.'},
                      {'role':'user','content':render(user)}]
            content=strip_fence(await self.completion('latex',messages,p.max_tokens))
        if not content: raise ValueError('LLM returned an empty LaTeX document')
        valid=all(part in content for part in ('\\documentclass','\\begin{document}','\\end{document}'))
        if not valid or content.count('{')!=content.count('}'):
            await self.sidecar.log('warning','Generated LaTeX may require compiler repair')
        data=content.encode('utf-8')
        await self.sidecar.save_artifact(artifact_name='output',filename='output.tex',content_type='application/x-tex',data=data)
        return {'latex':data,'metadata':json.dumps({'subject':subject,'segments':p.segments}).encode()}
