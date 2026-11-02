import asyncio
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import tempfile

_MAX_INPUT=256*1048576


async def tool(command,directory,timeout,sidecar=None):
    executable=shutil.which(command[0])
    if not executable: raise RuntimeError('Required native tool is not installed')
    try:
        with (directory/'tool.log').open('wb') as log:
            process=await asyncio.create_subprocess_exec(executable,*command[1:],cwd=directory,
                env={'PATH':os.defpath,'HOME':str(directory),'TMPDIR':str(directory)},
                stdout=log,stderr=log,start_new_session=True)
            try: await asyncio.wait_for(process.wait(),timeout)
            except BaseException:
                if process.returncode is None:
                    try: os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                await process.wait()
                raise
    except BaseException:
        if sidecar is not None and hasattr(sidecar,'log'):
            from generated.runtime_logs import report_file_log
            try: await report_file_log(sidecar,directory/'tool.log',tool=command[0])
            except Exception: pass
        raise
    if sidecar is not None and hasattr(sidecar,'log'):
        from generated.runtime_logs import report_file_log
        await report_file_log(sidecar,directory/'tool.log',tool=command[0])
    if process.returncode: raise ValueError('Audio decode or segmentation failed')


class PluginHandler:
    def __init__(self,context,sidecar):
        self.context,self.sidecar=context,sidecar
        self.directory=None; self.stream=None; self.size=0

    async def on_start(self):
        p=self.context.parameters
        if (type(p.chunk_duration_minutes) is not int or not 1<=p.chunk_duration_minutes<=120
                or type(p.max_chunk_bytes) is not int or not 4096<=p.max_chunk_bytes<=7*1048576
                or type(p.max_chunks) is not int or not 1<=p.max_chunks<=256
                or type(p.tool_timeout) is not int or not 1<=p.tool_timeout<=300
                or not isinstance(p.language,str) or not re.fullmatch(r'(?:auto|[a-z]{2,3}(?:-[A-Za-z]{2})?)',p.language)):
            raise ValueError('Invalid transcription limits or language')
        self.directory=tempfile.TemporaryDirectory(prefix='stt-')
        self.path=Path(self.directory.name)
        self.stream=(self.path/'input').open('wb')

    async def process_buffer(self,buffer):
        if self.size+len(buffer)>_MAX_INPUT: raise ValueError('Audio input exceeds 256 MiB limit')
        self.stream.write(buffer); self.size+=len(buffer)

    async def on_cleanup(self):
        if self.stream is not None: self.stream.close(); self.stream=None
        if self.directory is not None: self.directory.cleanup(); self.directory=None

    async def on_finish(self):
        if not self.size: raise ValueError('Audio input is empty')
        self.stream.close(); self.stream=None
        p=self.context.parameters
        await tool(['ffprobe','-v','error','-show_entries','format=duration','-of','json',
                    '-o',str(self.path/'probe.json'),str(self.path/'input')],self.path,p.tool_timeout,self.sidecar)
        duration=float(json.loads((self.path/'probe.json').read_text())['format']['duration'])
        if not math.isfinite(duration) or duration<=0: raise ValueError('Invalid audio duration')
        parts=[]; count=0; chars=0

        async def transcribe(start,length):
            nonlocal count,chars
            target=self.path/'chunk.mp3'
            await tool(['ffmpeg','-nostdin','-v','error','-y','-protocol_whitelist','file,pipe',
                '-ss',str(start),'-i',str(self.path/'input'),'-t',str(length),'-vn','-threads','1',
                '-ar','16000','-ac','1','-c:a','libmp3lame','-b:a','64k','-f','mp3',str(target)],self.path,p.tool_timeout,self.sidecar)
            if target.stat().st_size>p.max_chunk_bytes:
                target.unlink()
                if length<=.25: raise ValueError('Audio chunk cannot fit the configured size limit')
                await transcribe(start,length/2)
                await transcribe(start+length/2,length-length/2)
                return
            if count>=p.max_chunks: raise ValueError('Maximum transcription chunk count exceeded')
            count+=1
            data=target.read_bytes(); target.unlink()
            text=(await self.sidecar.transcribe(data,model=p.model,language=p.language,content_type='audio/mpeg')).strip()
            chars+=len(text.encode('utf-8'))
            if chars>4194304: raise ValueError('Transcript exceeds limit')
            if text: parts.append(text)

        position=0.0
        while position<duration:
            length=min(p.chunk_duration_minutes*60,duration-position)
            await transcribe(position,length)
            position+=length
        transcript=' '.join(parts)
        if not transcript: raise ValueError('No speech transcript to save')
        data=transcript.encode('utf-8')
        await self.sidecar.save_artifact(artifact_name='output',filename='transcript.txt',content_type='text/plain',data=data)
        return {'transcript':data,'metadata':json.dumps({'duration_ms':round(duration*1000),
            'language':p.language,'chunks':count}).encode()}
