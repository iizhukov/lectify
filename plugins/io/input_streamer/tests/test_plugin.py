import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def handler():
    spec = importlib.util.spec_from_file_location('input_source_business', Path(__file__).parents[1] / 'src/plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(file_id='file-1', chunk_size_bytes=4)), SimpleNamespace())


@pytest.mark.asyncio
async def test_source_yields_each_chunk_without_reading_entire_file(handler):
    calls = []
    async def read_file(**request):
        calls.append(request)
        yield b'abcd'
        yield b'ef'
    handler.sidecar.read_file = read_file
    await handler.on_start()
    stream = handler.produce()
    assert await anext(stream) == {'data_stream': b'abcd'}
    assert await anext(stream) == {'data_stream': b'ef'}
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert calls == [{'file_id': 'file-1', 'chunk_size_bytes': 4}]


@pytest.mark.asyncio
async def test_source_propagates_storage_failure(handler):
    async def read_file(**request):
        raise RuntimeError('storage unavailable')
        yield b''
    handler.sidecar.read_file = read_file
    with pytest.raises(RuntimeError, match='storage unavailable'):
        await anext(handler.produce())


@pytest.mark.asyncio
@pytest.mark.parametrize('file_id,size', [('', 4), ('x'*129, 4), ('id', 0), ('id', 1048577), ('id', True)])
async def test_source_rejects_invalid_parameters(handler, file_id, size):
    handler.context.parameters.file_id = file_id
    handler.context.parameters.chunk_size_bytes = size
    with pytest.raises(ValueError):
        await handler.on_start()
