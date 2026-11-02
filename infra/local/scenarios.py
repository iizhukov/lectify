"""Monolith parity probes against real local services and explicitly offline provider."""
import asyncio
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import wave
import yaml

sys.path.insert(0,'/app/services/tools/client')
from generated.grpc_client.grpc_clients import GrpcClients
from generated.protos.clients.api_auth import index_pb2 as auth_pb, index_pb2_grpc as auth_rpc
from generated.protos.clients.api_prompt import index_pb2 as prompt_pb, index_pb2_grpc as prompt_rpc
from generated.protos.clients.api_workflow import index_pb2 as wf_pb, index_pb2_grpc as wf_rpc
from generated.protos.clients.api_execution import index_pb2 as ex_pb, index_pb2_grpc as ex_rpc
from generated.protos.clients.orchestrator import index_pb2 as orch_pb, index_pb2_grpc as orch_rpc
from generated.protos.clients.api_file import index_pb2 as file_pb, index_pb2_grpc as file_rpc
from backend import PLUGINS
from seed import main as seed_library


def node(id,plugin,version='1.0.0',parameters=None,mapping=()):
    return wf_pb.GraphNode(id=id,plugin_id=plugin,plugin_version=version,
        parameters_json=json.dumps(parameters or {}),input_mapping=list(mapping))


def edge(source,output,target,input):
    return wf_pb.GraphEdge(from_node_id=source,from_output=output,to_node_id=target,to_input=input)


async def main():
    if not json.loads(Path('/run/config/mode.json').read_text()).get('offline_test_provider'):
        raise RuntimeError('Run backend.py up --test-provider first; parity probes never call paid models')
    await seed_library()
    clients=GrpcClients(source_service='tools_client')
    try:
        auth=auth_rpc.AuthServiceStub(clients.channel('api_auth'))
        secrets=json.loads(Path('/run/config/secrets.json').read_text())
        login=await auth.Login(auth_pb.LoginRequest(username='admin',password=secrets['admin']),timeout=15)
        metadata=(('x-user-authorization','Bearer '+login.access_token),)
        registry=orch_rpc.OrchestratorServiceStub(clients.channel('orchestrator'))
        for relative in PLUGINS.values():
            manifest=yaml.safe_load((Path('/app/plugins')/relative/'plugin.yaml').read_text())
            await registry.RegisterPluginManifest(orch_pb.RegisterPluginManifestRequest(plugin_id=manifest['plugin']['name'],
                version=manifest['plugin']['version'],manifest_yaml=json.dumps(manifest)),metadata=metadata,timeout=20)
        workflows=wf_rpc.WorkflowServiceStub(clients.channel('api_workflow'))
        executions=ex_rpc.ExecutionServiceStub(clients.channel('api_execution'))
        files=file_rpc.FileServiceStub(clients.channel('api_file'))
        prompts=prompt_rpc.PromptServiceStub(clients.channel('api_prompt'))

        async def run(name,nodes,edges,inputs,expect='EXECUTION_STATE_COMPLETED',workflow=None):
            if workflow is None:
                workflow=await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name=name,
                    graph=wf_pb.WorkflowGraph(nodes=nodes,edges=edges)),metadata=metadata,timeout=20)
            started=await executions.StartWorkflow(ex_pb.StartWorkflowRequest(workflow_id=workflow.id,
                expected_version=workflow.version,request_key=uuid.uuid4().hex,initial_inputs=inputs),metadata=metadata,timeout=30)
            async with asyncio.timeout(180):
                while True:
                    result=await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=started.execution_id),metadata=metadata,timeout=15)
                    if result.state in ('EXECUTION_STATE_FAILED','EXECUTION_STATE_CANCELLED','EXECUTION_STATE_COMPLETED'): break
                    await asyncio.sleep(.5)
            assert result.state==expect,result.error_message
            return result

        async def download(id):
            frames=[frame async for frame in files.Download(file_pb.FileRequest(id=id),metadata=metadata,timeout=20)]
            assert frames[-1].is_last
            return b''.join(frame.chunk for frame in frames if frame.WhichOneof('data')=='chunk')

        prompt=await prompts.CreatePrompt(prompt_pb.CreatePromptRequest(name='Parity prompt',
            system_prompt='Respond for {{name}}',user_prompt_template='{{transcript}}',variables=['name','transcript']),
            metadata=metadata,timeout=15)
        result=await run('Prompt selector and LLM request',[
            node('text','text_input','0.1.0',mapping=[wf_pb.InputMapping(target_field='value',source='input.text',transform='passthrough')]),
            node('prompt','prompt_selector',parameters={'prompt_id':prompt.id}),
            node('llm','llm_request',parameters={'values':{'name':'Alice'}}),
            node('output','text_output','0.1.0')],
            [edge('text','text','llm','text'),edge('prompt','prompt','llm','prompt'),edge('llm','response','output','text')],
            {'text':'Hello {{name}}'})
        output=next(item for item in result.nodes if item.node_id=='output')
        assert await download(output.output_artifacts['result'])==b'LOCAL TEST RESPONSE: Hello {{name}}'
        print('PASS: prompt library → authorized selector → joined text/template → LLM HTTP fixture → saved result')

        text='Текст лекции: {{name}} остаётся данными.'
        data=b'\xef\xbb\xbf'+text.encode('utf-8')
        async def text_frames():
            yield file_pb.UploadFrame(sequence=0,metadata=file_pb.UploadMetadata(filename='lecture.txt',content_type='text/plain',
                size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
            yield file_pb.UploadFrame(sequence=1,chunk=data,is_last=True)
        text_file=await files.Upload(text_frames(),metadata=metadata,timeout=15)
        result=await run('Monolith text file to Markdown',[
            node('input','input',parameters={'input_type':'text'},mapping=[wf_pb.InputMapping(
                target_field='file_id',source='input.file',transform='passthrough')]),
            node('prompt','prompt_selector',parameters={'prompt_id':prompt.id}),
            node('md','text_to_md',parameters={'max_chars':40000,'style':'academic','values':{'name':'Alice'}})],
            [edge('input','text','md','text'),edge('prompt','prompt','md','prompt')],{'file':text_file.id})
        output=next(item for item in result.nodes if item.node_id=='md')
        assert await download(output.output_artifacts['output'])==('LOCAL TEST RESPONSE: '+text).encode()
        print('PASS: typed file input/MIME/UTF-8 BOM → library prompt → text_to_md@1.0.0 → S3 Markdown')

        invalid_workflow=await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name='MIME mismatch',graph=wf_pb.WorkflowGraph(
            nodes=[node('input','input',parameters={'input_type':'audio'},mapping=[wf_pb.InputMapping(
                target_field='file_id',source='input.file',transform='passthrough')])])),metadata=metadata,timeout=20)
        invalid_run=await executions.StartWorkflow(ex_pb.StartWorkflowRequest(workflow_id=invalid_workflow.id,
            expected_version=invalid_workflow.version,request_key=uuid.uuid4().hex,initial_inputs={'file':text_file.id}),
            metadata=metadata,timeout=20)
        async with asyncio.timeout(60):
            while True:
                rejected=await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=invalid_run.execution_id),metadata=metadata,timeout=15)
                if rejected.state in ('EXECUTION_STATE_FAILED','EXECUTION_STATE_COMPLETED'): break
                await asyncio.sleep(.5)
        assert rejected.state=='EXECUTION_STATE_FAILED'
        assert not any(item.output_artifacts for item in rejected.nodes)
        print('PASS: text file rejected by audio-only input; no success artifact')

        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(b'\0\0'*16000)
        data=buffer.getvalue()
        async def frames():
            yield file_pb.UploadFrame(sequence=0,metadata=file_pb.UploadMetadata(filename='audio.wav',content_type='audio/wav',
                size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
            yield file_pb.UploadFrame(sequence=1,chunk=data,is_last=True)
        source=await files.Upload(frames(),metadata=metadata,timeout=15)
        result=await run('Media conversion',[
            node('input','file_input','0.1.0',mapping=[wf_pb.InputMapping(target_field='file_id',source='input.file',transform='passthrough')]),
            node('convert','media_converter','1.1.0')],[edge('input','data','convert','media')],{'file':source.id})
        output=next(item for item in result.nodes if item.node_id=='convert')
        converted=await download(output.output_artifacts['output'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'output.m4a'; path.write_bytes(converted)
            probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],
                check=True,capture_output=True,text=True,timeout=10)
            assert .9<=float(json.loads(probe.stdout)['format']['duration'])<=1.2
        assert b'ftyp' in converted[:16]
        print('PASS: uploaded WAV → scoped file read → real FFmpeg M4A → S3 → independent ffprobe')

        with tempfile.TemporaryDirectory() as directory:
            video_path=Path(directory)/'source.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=c=black:s=64x64:r=10',
                '-f','lavfi','-i','anullsrc=r=44100:cl=mono','-t','1','-c:v','mpeg4','-c:a','aac','-shortest',str(video_path)],
                check=True,capture_output=True,timeout=20)
            video=video_path.read_bytes()
        async def video_frames():
            yield file_pb.UploadFrame(sequence=0,metadata=file_pb.UploadMetadata(filename='source.mp4',content_type='video/mp4',
                size_bytes=len(video),sha256=hashlib.sha256(video).hexdigest()))
            yield file_pb.UploadFrame(sequence=1,chunk=video,is_last=True)
        video_file=await files.Upload(video_frames(),metadata=metadata,timeout=15)
        result=await run('Video to audio',[
            node('input','input',parameters={'input_type':'video'},mapping=[wf_pb.InputMapping(
                target_field='file_id',source='input.file',transform='passthrough')]),node('convert','media_converter','1.1.0')],
            [edge('input','data','convert','media')],{'file':video_file.id})
        video_audio=await download(next(item for item in result.nodes if item.node_id=='convert').output_artifacts['output'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'audio.m4a'; path.write_bytes(video_audio)
            probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type','-of','json',str(path)],
                check=True,capture_output=True,text=True,timeout=10)
            assert [stream['codec_type'] for stream in json.loads(probe.stdout)['streams']]==['audio']
        print('PASS: actual MP4 video/audio → video MIME input → FFmpeg extraction → audio-only M4A')

        for kind,file_id in [('audio',source.id),('video',video_file.id)]:
            result=await run(kind+' to transcript, Markdown and PDF',[
                node('input','input',parameters={'input_type':kind},mapping=[wf_pb.InputMapping(
                    target_field='file_id',source='input.file',transform='passthrough')]),
                node('convert','media_converter','1.1.0'),node('stt','speech_to_text','1.1.0'),
                node('prompt','prompt_selector',parameters={'prompt_id':prompt.id}),
                node('md','text_to_md',parameters={'values':{'name':'Alice'}}),
                node('latex','text_to_latex'),node('pdf','latex_to_pdf')],
                [edge('input','data','convert','media'),edge('convert','audio','stt','audio'),
                 edge('stt','transcript','md','text'),edge('prompt','prompt','md','prompt'),
                 edge('stt','transcript','latex','text'),edge('latex','latex','pdf','latex')],{'file':file_id})
            outputs={item.node_id:item.output_artifacts for item in result.nodes}
            assert await download(outputs['stt']['output'])==b'LOCAL TEST TRANSCRIPT'
            assert await download(outputs['md']['output'])==b'LOCAL TEST RESPONSE: LOCAL TEST TRANSCRIPT'
            pdf=await download(outputs['pdf']['output'])
            assert pdf.startswith(b'%PDF-')
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'pipeline.pdf'; path.write_bytes(pdf)
                parsed=subprocess.run(['pdftotext',str(path),'-'],check=True,capture_output=True,text=True,timeout=10)
                assert 'Offline LaTeX notes' in parsed.stdout
            print('PASS: '+kind+' → FFmpeg → STT → DAG fanout → prompt/Markdown + LaTeX/real PDF → S3')

        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
            audio.writeframes(b'\0\0'*16000*61)
        segmented=buffer.getvalue()
        async def segmented_frames():
            yield file_pb.UploadFrame(sequence=0,metadata=file_pb.UploadMetadata(filename='long.wav',content_type='audio/wav',
                size_bytes=len(segmented),sha256=hashlib.sha256(segmented).hexdigest()))
            for sequence,offset in enumerate(range(0,len(segmented),65536),1):
                yield file_pb.UploadFrame(sequence=sequence,chunk=segmented[offset:offset+65536],is_last=offset+65536>=len(segmented))
        long_file=await files.Upload(segmented_frames(),metadata=metadata,timeout=30)
        result=await run('STT time and size splitting',[
            node('input','input',parameters={'input_type':'audio'},mapping=[wf_pb.InputMapping(
                target_field='file_id',source='input.file',transform='passthrough')]),
            node('convert','media_converter','1.1.0'),
            node('stt','speech_to_text','1.1.0',parameters={'chunk_duration_minutes':1,'max_chunk_bytes':262144})],
            [edge('input','data','convert','media'),edge('convert','audio','stt','audio')],{'file':long_file.id})
        transcript=await download(next(item for item in result.nodes if item.node_id=='stt').output_artifacts['output'])
        assert transcript==b' '.join([b'LOCAL TEST TRANSCRIPT']*3),transcript
        print('PASS: 61-second WAV → time limit + encoded-byte bisection → three ordered provider calls → transcript')

        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(48000)
            audio.writeframes(b'\0\0'*48000*200)
        large=buffer.getvalue()
        assert len(large)>16*1048576
        async def large_frames():
            yield file_pb.UploadFrame(sequence=0,metadata=file_pb.UploadMetadata(filename='large.wav',content_type='audio/wav',
                size_bytes=len(large),sha256=hashlib.sha256(large).hexdigest()))
            for sequence,offset in enumerate(range(0,len(large),65536),1):
                yield file_pb.UploadFrame(sequence=sequence,chunk=large[offset:offset+65536],is_last=offset+65536>=len(large))
        large_file=await files.Upload(large_frames(),metadata=metadata,timeout=60)
        result=await run('Input exceeds runtime full-buffer limit',[
            node('input','input',parameters={'input_type':'audio'},mapping=[wf_pb.InputMapping(
                target_field='file_id',source='input.file',transform='passthrough')]),
            node('convert','media_converter','1.1.0'),node('stt','speech_to_text','1.1.0')],
            [edge('input','data','convert','media'),edge('convert','audio','stt','audio')],{'file':large_file.id})
        assert await download(next(item for item in result.nodes if item.node_id=='stt').output_artifacts['output'])==b'LOCAL TEST TRANSCRIPT'
        converted_node=next(item for item in result.nodes if item.node_id=='convert')
        assert converted_node.bytes_streamed_in==len(large)
        print('PASS: 19.2 MB WAV → bounded input frames/spooled FFmpeg → streamed audio → STT → saved transcript')

        result=await run('Text to LaTeX and PDF',[
            node('input','input',parameters={'input_type':'text'},mapping=[wf_pb.InputMapping(
                target_field='file_id',source='input.file',transform='passthrough')]),
            node('latex','text_to_latex'),node('pdf','latex_to_pdf')],
            [edge('input','text','latex','text'),edge('latex','latex','pdf','latex')],{'file':text_file.id})
        latex_node=next(item for item in result.nodes if item.node_id=='latex')
        assert b'\\documentclass' in await download(latex_node.output_artifacts['output'])
        pdf_node=next(item for item in result.nodes if item.node_id=='pdf')
        pdf=await download(pdf_node.output_artifacts['output'])
        assert pdf.startswith(b'%PDF-')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'document.pdf'; path.write_bytes(pdf)
            parsed=subprocess.run(['pdftotext',str(path),'-'],check=True,capture_output=True,text=True,timeout=10)
            assert 'Offline LaTeX notes' in parsed.stdout
        print('PASS: typed text input → classified LaTeX generation → real pdflatex → S3 PDF → independent pdftotext')

        broken=r'\documentclass{article}\begin{document}\undefinedcommand\end{document}'
        result=await run('PDF compiler repair',[
            node('text','text_input','0.1.0',mapping=[wf_pb.InputMapping(target_field='value',source='input.latex',transform='passthrough')]),
            node('pdf','latex_to_pdf',parameters={'max_attempts':2,'use_llm_repair':True})],
            [edge('text','text','pdf','latex')],{'latex':broken})
        repaired=next(item for item in result.nodes if item.node_id=='pdf')
        repaired_pdf=await download(repaired.output_artifacts['output'])
        assert repaired_pdf.startswith(b'%PDF-')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'repaired.pdf'; path.write_bytes(repaired_pdf)
            parsed=subprocess.run(['pdftotext',str(path),'-'],check=True,capture_output=True,text=True,timeout=10)
            assert 'Offline LaTeX notes' in parsed.stdout
        print('PASS: actual compiler error → offline LLM repair → second real compilation → saved PDF')

        russian=(r'\documentclass{article}\usepackage{cmap}\usepackage[T2A]{fontenc}'
                 r'\usepackage[utf8]{inputenc}\usepackage[russian]{babel}'
                 r'\begin{document}Конспект лекции.\end{document}')
        result=await run('Cyrillic PDF without model repair',[
            node('text','text_input','0.1.0',mapping=[wf_pb.InputMapping(target_field='value',source='input.latex',transform='passthrough')]),
            node('pdf','latex_to_pdf',parameters={'max_attempts':1,'use_llm_repair':False})],
            [edge('text','text','pdf','latex')],{'latex':russian})
        cyrillic=await download(next(item for item in result.nodes if item.node_id=='pdf').output_artifacts['output'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'russian.pdf'; path.write_bytes(cyrillic)
            parsed=subprocess.run(['pdftotext',str(path),'-'],check=True,capture_output=True,text=True,timeout=10)
            assert 'Конспект' in parsed.stdout
        print('PASS: Russian LaTeX → real PDF without LLM repair → extracted Cyrillic text')

        pdf_nodes=[node('text','text_input','0.1.0',mapping=[wf_pb.InputMapping(
            target_field='value',source='input.latex',transform='passthrough')]),
            node('pdf','latex_to_pdf',parameters={'max_attempts':1,'use_llm_repair':False})]
        rejected=await run('Compiler failure without repair',pdf_nodes,[edge('text','text','pdf','latex')],
            {'latex':broken},expect='EXECUTION_STATE_FAILED')
        assert not any(item.output_artifacts for item in rejected.nodes)
        print('PASS: real compiler error without repair → FAILED, no success PDF')

        pdf_nodes[-1]=node('pdf','latex_to_pdf',parameters={'max_attempts':1,'use_llm_repair':False,'compile_timeout':1})
        loop=r'\documentclass{article}\begin{document}\loop\iftrue\repeat\end{document}'
        rejected=await run('Compiler timeout',pdf_nodes,[edge('text','text','pdf','latex')],
            {'latex':loop},expect='EXECUTION_STATE_FAILED')
        assert not any(item.output_artifacts for item in rejected.nodes)
        print('PASS: actual nonterminating TeX → bounded timeout/cleanup → FAILED, no artifact')

        library={}; offset=0
        while True:
            page=await workflows.ListWorkflows(wf_pb.ListRequest(page_size=100,offset=offset),metadata=metadata,timeout=20)
            library.update({row.name:row for row in page.workflows if not row.owner_id and row.name.startswith('Lectify: ')})
            if not page.next_offset: break
            offset=page.next_offset
        assert len(library)==5
        for name,saved in library.items():
            kind,output=name.removeprefix('Lectify: ').split(' → ')
            copy=await workflows.ForkWorkflow(wf_pb.ForkWorkflowRequest(id=saved.id,expected_version=saved.version,
                name='Own copy: '+name),metadata=metadata,timeout=20)
            assert copy.id!=saved.id and copy.owner_id
            result=await run(name,[],[],{'file':{'text':text_file.id,'audio':source.id,'video':video_file.id}[kind]},workflow=copy)
            outputs={item.node_id:item.output_artifacts for item in result.nodes}
            if output=='markdown':
                assert (await download(outputs['notes']['output'])).startswith(b'LOCAL TEST RESPONSE: ')
            else: assert (await download(outputs['pdf']['output'])).startswith(b'%PDF-')
            original=await workflows.GetWorkflow(wf_pb.IdRequest(id=saved.id),metadata=metadata,timeout=20)
            assert original.version==saved.version and original.graph==saved.graph
            print('PASS: seeded library → owned fork → '+kind+' → '+output+'; shared graph unchanged')
    finally:
        await clients.close_all()


if __name__=='__main__': asyncio.run(main())
