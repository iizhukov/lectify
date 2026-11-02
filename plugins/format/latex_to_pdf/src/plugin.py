import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import signal
import tempfile


class PluginHandler:
    def __init__(self, context, sidecar):
        self.context,self.sidecar=context,sidecar
        self.source=bytearray()

    async def on_start(self):
        p=self.context.parameters
        if (type(p.max_attempts) is not int or not 1<=p.max_attempts<=5 or type(p.use_llm_repair) is not bool
                or type(p.compile_timeout) is not int or not 1<=p.compile_timeout<=120
                or type(p.repair_timeout) is not int or not 1<=p.repair_timeout<=300):
            raise ValueError('Invalid PDF compilation limits')

    async def process_buffer(self, buffer):
        if len(self.source)+len(buffer)>1048576: raise ValueError('LaTeX source exceeds limit')
        self.source.extend(buffer)

    async def compile(self, directory):
        executable=shutil.which('pdflatex')
        if not executable: raise RuntimeError('pdflatex is not installed')
        pdf=directory/'document.pdf'
        pdf.unlink(missing_ok=True)
        with (directory/'compile.log').open('wb') as log:
            process=await asyncio.create_subprocess_exec(executable,'-no-shell-escape','-interaction=nonstopmode',
                '-halt-on-error','-file-line-error','-output-directory',str(directory),'document.tex',cwd=directory,
                env={'PATH':os.defpath,'HOME':str(directory),'TMPDIR':str(directory),
                     'openin_any':'p','openout_any':'p','TEXMFOUTPUT':str(directory),'TEXMFVAR':str(directory/'texmf-var')},
                stdout=log,stderr=log,start_new_session=True)
            try: await asyncio.wait_for(process.wait(),self.context.parameters.compile_timeout)
            except BaseException:
                if process.returncode is None:
                    try: os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                await process.wait()
                if hasattr(self.sidecar,'log'):
                    from generated.runtime_logs import report_file_log
                    try: await report_file_log(self.sidecar,directory/'compile.log',tool='pdflatex',stream='stdout')
                    except Exception: pass
                raise
        if hasattr(self.sidecar,'log'):
            from generated.runtime_logs import report_file_log
            await report_file_log(self.sidecar,directory/'compile.log',tool='pdflatex',stream='stdout')
        return process.returncode==0 and pdf.exists()

    async def repair(self, source, errors):
        parts=[]; size=0
        async with asyncio.timeout(self.context.parameters.repair_timeout):
            async for delta in self.sidecar.call_llm(model=self.context.parameters.model,purpose='latex_repair',
                    temperature=0,max_tokens=4096,messages=[
                        {'role':'system','content':'Исправь ошибки компиляции LaTeX. Верни только полный исправленный LaTeX-код.'},
                        {'role':'user','content':'Ошибки:\n'+errors[:2000]+'\n\nКод:\n'+source[:25000]}]):
                size+=len(delta.encode())
                if size>1048576: raise ValueError('Repaired LaTeX exceeds limit')
                parts.append(delta)
        content=''.join(parts).strip()
        match=re.fullmatch(r'```(?:latex|tex)?\s*\n?(.*?)\n?```',content,re.S)
        content=(match.group(1) if match else content).strip()
        if not content: raise ValueError('LLM repair returned empty LaTeX')
        return content

    async def on_finish(self):
        source=bytes(self.source).decode('utf-8')
        if not source.strip(): raise ValueError('LaTeX source is empty')
        self.source.clear()
        p=self.context.parameters
        with tempfile.TemporaryDirectory(prefix='latex-') as temp:
            directory=Path(temp)
            attempts=0
            while attempts<p.max_attempts:
                attempts+=1
                (directory/'document.tex').write_text(source,encoding='utf-8')
                if await self.compile(directory):
                    path=directory/'document.pdf'
                    if not 0<path.stat().st_size<=24*1048576: raise ValueError('Compiled PDF exceeds limit')
                    data=path.read_bytes()
                    if not data.startswith(b'%PDF-'): raise ValueError('Compiler did not produce a PDF')
                    break
                if not p.use_llm_repair or attempts==p.max_attempts:
                    raise ValueError('PDF compilation failed within the configured attempt limit')
                with (directory/'compile.log').open('rb') as log: errors=log.read(8192).decode('utf-8',errors='replace')
                source=await self.repair(source,errors)
        await self.sidecar.save_artifact(artifact_name='output',filename='document.pdf',content_type='application/pdf',data=data)
        return {'pdf':data,'metadata':json.dumps({'attempts':attempts}).encode()}
