import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.mark.asyncio
async def test_selected_file_is_streamed_without_accumulating_and_validated():
    spec = importlib.util.spec_from_file_location('file_input_handler',Path(__file__).parents[1]/'src/plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    async def read_file(**scope):
        calls.append(scope)
        yield b'first'
        yield b'second'
    handler = module.PluginHandler(None,SimpleNamespace(read_file=read_file))
    await handler.on_start()
    outputs = await handler.process_buffer(b'owned-file')
    assert calls == []
    assert [item async for item in outputs] == [{'data':b'first'}, {'data':b'second'}]
    assert calls == [{'file_id':'owned-file','chunk_size_bytes':65536}]
    await handler.on_finish()
    with pytest.raises(ValueError): await handler.process_buffer(b'other-file')
    for value in (b'', b' file', b'x'*129):
        with pytest.raises(ValueError):
            await module.PluginHandler(None,SimpleNamespace(read_file=read_file)).process_buffer(value)
