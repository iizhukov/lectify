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
    spec=importlib.util.spec_from_file_location('converter_business',Path(__file__).parents[1]/'src/plugin.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values=dict(format='m4a',bitrate='64k',sample_rate=44100,timeout=10)
    values.update(parameters)
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(**values)),SimpleNamespace(save_artifact=AsyncMock()))


@pytest.mark.asyncio
@pytest.mark.parametrize('format,mime',[('m4a','audio/mp4'),('mp3','audio/mpeg'),('wav','audio/wav')])
async def test_real_ffmpeg_conversion_and_duration(format,mime):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg and ffprobe are required for real media conversion')
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\x00\x00'*16000)
    plugin=handler(format=format)
    await plugin.on_start()
    await plugin.process_buffer(buffer.getvalue())
    result=await plugin.on_finish()
    assert len(result['audio'])>100
    metadata=json.loads(result['metadata'])
    assert 900<=metadata['duration_ms']<=1200
    assert metadata['sample_rate']==44100 and metadata['format']==format
    assert plugin.sidecar.save_artifact.call_args.kwargs['content_type']==mime
    assert plugin.sidecar.save_artifact.call_args.kwargs['data']==result['audio']


@pytest.mark.asyncio
async def test_invalid_parameters_empty_and_invalid_media_fail_without_artifact():
    plugin=handler(format='shell;command')
    with pytest.raises(ValueError): await plugin.on_start()
    plugin=handler()
    with pytest.raises(ValueError): await plugin.on_finish()
    if shutil.which('ffmpeg'):
        await plugin.on_start()
        await plugin.process_buffer(b'not media')
        with pytest.raises(ValueError): await plugin.on_finish()
    plugin.sidecar.save_artifact.assert_not_called()
