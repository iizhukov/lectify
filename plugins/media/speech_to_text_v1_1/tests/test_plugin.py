import importlib.util
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock
import wave
import pytest


def handler(**parameters):
    spec=importlib.util.spec_from_file_location('segmented_stt',Path(__file__).parents[1]/'src/plugin.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    values=dict(model='openai/gpt-4o-mini-transcribe',language='ru',chunk_duration_minutes=1,
                max_chunk_bytes=7*1048576,max_chunks=128,tool_timeout=15)
    values.update(parameters)
    sidecar=SimpleNamespace(save_artifact=AsyncMock(),transcribe=AsyncMock(side_effect=lambda *a,**k:' part '))
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(**values)),sidecar)


def audio(seconds):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
        stream.writeframes(b'\0\0'*16000*seconds)
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize('seconds,limit,expected',[(61,7*1048576,2),(3,16384,2)])
async def test_real_audio_split_by_duration_and_encoded_size(seconds,limit,expected):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): pytest.skip('FFmpeg required')
    plugin=handler(max_chunk_bytes=limit)
    await plugin.on_start(); path=plugin.path
    try:
        data=audio(seconds)
        for offset in range(0,len(data),65536): await plugin.process_buffer(data[offset:offset+65536])
        result=await plugin.on_finish()
        assert json.loads(result['metadata'])['chunks']==expected
        assert result['transcript']==(' '.join(['part']*expected)).encode()
        assert plugin.sidecar.transcribe.await_count==expected
        for call in plugin.sidecar.transcribe.call_args_list:
            assert 0<len(call.args[0])<=limit
            assert call.kwargs['content_type']=='audio/mpeg'
        assert plugin.sidecar.save_artifact.call_args.kwargs['data']==result['transcript']
    finally: await plugin.on_cleanup()
    assert not path.exists()


@pytest.mark.asyncio
async def test_chunk_limit_does_not_publish_partial_artifact():
    if not shutil.which('ffmpeg'): pytest.skip('FFmpeg required')
    plugin=handler(max_chunks=1,max_chunk_bytes=16384)
    await plugin.on_start(); path=plugin.path
    try:
        await plugin.process_buffer(audio(3))
        with pytest.raises(ValueError,match='chunk count'): await plugin.on_finish()
        plugin.sidecar.save_artifact.assert_not_called()
    finally: await plugin.on_cleanup()
    assert not path.exists()


@pytest.mark.asyncio
async def test_empty_transcription_and_provider_error_cleanup():
    if not shutil.which('ffmpeg'): pytest.skip('FFmpeg required')
    for response in ('   ',RuntimeError('provider failure')):
        plugin=handler(); await plugin.on_start(); path=plugin.path
        plugin.sidecar.transcribe=AsyncMock(return_value=response) if isinstance(response,str) else AsyncMock(side_effect=response)
        try:
            await plugin.process_buffer(audio(1))
            with pytest.raises((ValueError,RuntimeError)): await plugin.on_finish()
            plugin.sidecar.save_artifact.assert_not_called()
        finally: await plugin.on_cleanup()
        assert not path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('parameters',[{'max_chunk_bytes':0},{'chunk_duration_minutes':True},{'language':'ru;sh'},{'max_chunks':257}])
async def test_rejects_invalid_limits_before_opening_spool(parameters):
    plugin=handler(**parameters)
    with pytest.raises(ValueError): await plugin.on_start()
    assert plugin.directory is None
    plugin.sidecar.transcribe.assert_not_called()
