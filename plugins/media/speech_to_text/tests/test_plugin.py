import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def handler():
    spec = importlib.util.spec_from_file_location('stt_business', Path(__file__).parents[1]/'src/plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sidecar = SimpleNamespace(transcribe=AsyncMock(side_effect=['first segment', 'second segment']),
        log=AsyncMock(), report_progress=AsyncMock(), save_artifact=AsyncMock())
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(model='small-stt', language='ru')), sidecar)


@pytest.mark.asyncio
async def test_actual_transcription_stream_matches_saved_artifact(handler):
    await handler.on_start()
    first = await handler.process_buffer(b'audio1')
    second = await handler.process_buffer(b'audio2')
    await handler.on_finish()
    assert first['transcript_stream'] + second['transcript_stream'] == b'first segment second segment'
    assert handler.sidecar.save_artifact.call_args.kwargs['data'] == b'first segment second segment'
    assert handler.sidecar.save_artifact.call_args.kwargs['artifact_name'] == 'transcript_file'
    assert handler.sidecar.transcribe.call_args_list[0].kwargs == {'model': 'small-stt', 'language': 'ru'}


@pytest.mark.asyncio
async def test_agent_error_propagates_without_fake_transcript(handler):
    handler.sidecar.transcribe.side_effect = RuntimeError('agent unavailable')
    with pytest.raises(RuntimeError, match='agent unavailable'):
        await handler.process_buffer(b'audio')
    assert handler.transcripts == []
    handler.sidecar.save_artifact.assert_not_called()


@pytest.mark.asyncio
async def test_empty_input_does_not_call_agent_and_silence_cannot_save_fake_success(handler):
    assert await handler.process_buffer(b'') is None
    handler.sidecar.transcribe.assert_not_called()
    handler.sidecar.transcribe.side_effect = None
    handler.sidecar.transcribe.return_value = '  '
    assert await handler.process_buffer(b'audio') is None
    with pytest.raises(ValueError, match='No speech transcript'):
        await handler.on_finish()
    handler.sidecar.save_artifact.assert_not_called()
