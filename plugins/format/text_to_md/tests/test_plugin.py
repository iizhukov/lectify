import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def handler():
    spec = importlib.util.spec_from_file_location('markdown_business', Path(__file__).parents[1] / 'src/plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PluginHandler(
        SimpleNamespace(parameters=SimpleNamespace(title='Lecture')),
        SimpleNamespace(save_artifact=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_markdown_artifact_and_named_output(handler):
    assert await handler.on_start() == {'md_stream': b'# Lecture\n\n'}
    assert await handler.process_buffer('Текст'.encode()) == {'md_stream': 'Текст\n'.encode()}
    await handler.on_finish()
    assert handler.sidecar.save_artifact.call_args.kwargs == {
        'artifact_name': 'md_file', 'filename': 'notes.md', 'content_type': 'text/markdown',
        'data': '# Lecture\n\nТекст\n'.encode(),
    }


@pytest.mark.asyncio
async def test_no_success_without_input(handler):
    assert await handler.process_buffer(b'  ') == {'md_stream': b'  \n'}
    with pytest.raises(ValueError, match='No text'):
        await handler.on_finish()
    handler.sidecar.save_artifact.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_text_and_title(handler):
    with pytest.raises(UnicodeDecodeError):
        await handler.process_buffer(b'\xff')
    handler.context.parameters.title = 'Injected\nTitle'
    with pytest.raises(ValueError, match='single line'):
        await handler.on_start()


@pytest.mark.asyncio
async def test_blank_lines_preserved_and_stream_matches_artifact(handler):
    output = await handler.on_start()
    chunks = [output['md_stream']]
    for line in (b'Paragraph one', b'', b'Paragraph two'):
        output = await handler.process_buffer(line)
        chunks.append(output['md_stream'])
    await handler.on_finish()
    data = handler.sidecar.save_artifact.call_args.kwargs['data']
    assert b'Paragraph one\n\nParagraph two' in data
    assert b''.join(chunks) == data
