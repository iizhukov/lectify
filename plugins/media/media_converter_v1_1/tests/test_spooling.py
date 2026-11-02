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
    spec=importlib.util.spec_from_file_location('spooled_converter',Path(__file__).parents[1]/'src/plugin.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    values=dict(format='m4a',bitrate='64k',sample_rate=44100,timeout=20); values.update(parameters)
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(**values)),SimpleNamespace(save_artifact=AsyncMock()))


@pytest.mark.asyncio
async def test_large_input_spools_and_output_frames_are_bounded():
    if not shutil.which('ffmpeg'): pytest.skip('FFmpeg required')
    plugin=handler(); await plugin.on_start(); path=plugin.path
    try:
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(48000)
            audio.writeframes(b'\0\0'*48000*200)
        data=buffer.getvalue()
        assert len(data)>16*1048576
        for offset in range(0,len(data),65536): await plugin.process_buffer(data[offset:offset+65536])
        assert plugin.stream.tell()==len(data)
        frames=[frame async for frame in await plugin.on_finish()]
        encoded=b''.join(frame.get('audio',b'') for frame in frames)
        assert all(len(frame.get('audio',b''))<=65536 for frame in frames)
        assert 199000<=json.loads(frames[0]['metadata'])['duration_ms']<=201000
        assert encoded==plugin.sidecar.save_artifact.call_args.kwargs['data']
    finally: await plugin.on_cleanup()
    assert not path.exists()


@pytest.mark.asyncio
async def test_invalid_media_never_publishes_artifact_and_cleans_spool():
    if not shutil.which('ffmpeg'): pytest.skip('FFmpeg required')
    plugin=handler(); await plugin.on_start(); path=plugin.path
    try:
        await plugin.process_buffer(b'not media')
        with pytest.raises(ValueError):
            async for frame in await plugin.on_finish(): pass
        plugin.sidecar.save_artifact.assert_not_called()
    finally: await plugin.on_cleanup()
    assert not path.exists()
