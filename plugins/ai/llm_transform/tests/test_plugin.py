import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def handler():
    spec = importlib.util.spec_from_file_location(
        'llm_transform_business', Path(__file__).parents[1] / 'src/plugin.py',
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = SimpleNamespace(parameters=SimpleNamespace(
        model='small-model', prompt_template='Structure notes', temperature=0.2,
    ))
    sidecar = SimpleNamespace(log=AsyncMock(), report_progress=AsyncMock(), save_artifact=AsyncMock())
    return module.PluginHandler(context, sidecar)


@pytest.mark.asyncio
async def test_transforms_using_agent_and_saves_actual_completion(handler):
    requests = []

    async def completion(**request):
        requests.append(request)
        yield '# Notes\n'
        yield 'Actual model response'

    handler.sidecar.call_llm = completion
    await handler.on_start()
    output = await handler.process_buffer(b'Original lecture')
    assert output == {'transformed_stream': b'# Notes\nActual model response'}
    await handler.on_finish()
    assert requests == [{
        'model': 'small-model', 'temperature': 0.2, 'purpose': 'transform',
        'messages': [
            {'role': 'system', 'content': 'Structure notes'},
            {'role': 'user', 'content': 'Original lecture'},
        ],
    }]
    assert handler.sidecar.save_artifact.call_args.kwargs['data'] == b'# Notes\nActual model response'


@pytest.mark.asyncio
async def test_partial_failure_does_not_accept_partial_response(handler):
    async def completion(**request):
        yield 'partial'
        raise RuntimeError('agent unavailable')

    handler.sidecar.call_llm = completion
    with pytest.raises(RuntimeError, match='agent unavailable'):
        await handler.process_buffer(b'lecture')
    assert handler.transformed_paragraphs == []
    handler.sidecar.save_artifact.assert_not_called()


@pytest.mark.asyncio
async def test_empty_completion_fails(handler):
    async def completion(**request):
        yield '  '

    handler.sidecar.call_llm = completion
    with pytest.raises(ValueError, match='empty transformation'):
        await handler.process_buffer(b'lecture')
    assert handler.transformed_paragraphs == []


@pytest.mark.asyncio
async def test_empty_input_skipped_and_invalid_utf8_rejected(handler):
    handler.sidecar.call_llm = AsyncMock()
    await handler.process_buffer(b'  ')
    handler.sidecar.call_llm.assert_not_called()
    with pytest.raises(UnicodeDecodeError):
        await handler.process_buffer(b'\xff')


@pytest.mark.asyncio
async def test_no_input_cannot_produce_successful_artifact(handler):
    with pytest.raises(ValueError, match="No transformed text"):
        await handler.on_finish()
    handler.sidecar.save_artifact.assert_not_called()
