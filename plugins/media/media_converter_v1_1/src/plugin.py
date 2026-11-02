import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile

_INPUT_LIMIT = 256*1048576
_OUTPUT_LIMIT = 64*1048576
_FORMATS = {'m4a':('ipod','aac','audio/mp4'),'mp3':('mp3','libmp3lame','audio/mpeg'),
            'wav':('wav','pcm_s16le','audio/wav')}


async def run_tool(command,directory,timeout,sidecar=None):
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
    if process.returncode: raise ValueError('Media conversion or probing failed')


class PluginHandler:
    def __init__(self, context, sidecar):
        self.context,self.sidecar = context,sidecar
        self.directory = None
        self.stream = None
        self.size = 0

    async def on_start(self):
        p = self.context.parameters
        if (p.format not in _FORMATS or p.bitrate not in ('32k','64k','128k','256k')
                or type(p.sample_rate) is not int or p.sample_rate not in (22050,44100,48000)
                or type(p.timeout) is not int or not 1<=p.timeout<=300):
            raise ValueError('Invalid media conversion parameters')
        self.directory = tempfile.TemporaryDirectory(prefix='media-')
        self.path = Path(self.directory.name)
        self.stream = (self.path/'input').open('wb')

    async def process_buffer(self, buffer):
        if self.size+len(buffer)>_INPUT_LIMIT:
            raise ValueError('Media input exceeds 256 MiB limit')
        self.stream.write(buffer)
        self.size += len(buffer)

    async def on_cleanup(self):
        if self.stream is not None: self.stream.close(); self.stream = None
        if self.directory is not None: self.directory.cleanup(); self.directory = None

    async def on_finish(self):
        if not self.size:
            raise ValueError('Media input is empty')
        self.stream.close(); self.stream = None
        p = self.context.parameters
        muxer,codec,content_type = _FORMATS[p.format]
        async def outputs():
            directory = self.path
            source, target = directory/'input', directory/('output.'+p.format)
            command = ['ffmpeg','-nostdin','-v','error','-y','-protocol_whitelist','file,pipe',
                '-i',str(source),'-vn','-threads','1','-ar',str(p.sample_rate),'-c:a',codec]
            if p.format!='wav': command += ['-b:a',p.bitrate]
            command += ['-fs',str(_OUTPUT_LIMIT+1),'-f',muxer,str(target)]
            await run_tool(command,directory,p.timeout,self.sidecar)
            if not target.exists() or not 0<target.stat().st_size<=_OUTPUT_LIMIT:
                raise ValueError('Converted media is empty or exceeds limit')
            probe = directory/'probe.json'
            await run_tool(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries','format=duration',
                '-of','json','-o',str(probe),str(target)],directory,p.timeout,self.sidecar)
            duration = float(json.loads(probe.read_text())['format']['duration'])
            await self.sidecar.save_artifact(artifact_name='output',filename='output.'+p.format,
                content_type=content_type,data=target.read_bytes())
            yield {'metadata':json.dumps({'format':p.format,'duration_ms':round(duration*1000),
                'sample_rate':p.sample_rate}).encode()}
            with target.open('rb') as stream:
                while chunk := stream.read(65536): yield {'audio':chunk}
        return outputs()
