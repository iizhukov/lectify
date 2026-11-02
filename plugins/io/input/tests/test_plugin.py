import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest


def handler(kind='any',mime='text/plain; charset=utf-8'):
    spec=importlib.util.spec_from_file_location('legacy_input_business',Path(__file__).parents[1]/'src/plugin.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    reads=[]
    async def read_file(file_id,**options):
        reads.append(file_id)
        data='Привет'.encode('utf-8')
        for byte in data: yield bytes([byte])
    sidecar=SimpleNamespace(get_file_info=AsyncMock(return_value=dict(file_id='owned',filename='source.txt',
        content_type=mime,size_bytes=12,sha256='a'*64)),read_file=read_file)
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(input_type=kind)),sidecar),reads


@pytest.mark.asyncio
async def test_authorized_metadata_and_incremental_utf8_outputs():
    plugin,reads=handler('text')
    await plugin.on_start()
    outputs=await plugin.process_buffer(b'owned')
    assert reads==[]
    frames=[frame async for frame in outputs]
    assert b''.join(frame.get('data',b'') for frame in frames)=='Привет'.encode()
    assert b''.join(frame.get('text',b'') for frame in frames)=='Привет'.encode()
    assert json.loads(frames[0]['metadata'])['filename']=='source.txt'
    assert reads==['owned']
    await plugin.on_finish()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,mime',[('audio','text/plain'),('pdf','application/pdfevil'),('video','image/png')])
async def test_mime_mismatch_rejected_before_reading_file(kind,mime):
    plugin,reads=handler(kind,mime)
    await plugin.on_start()
    with pytest.raises(ValueError,match='MIME'): await plugin.process_buffer(b'owned')
    assert reads==[]


@pytest.mark.asyncio
async def test_missing_and_duplicate_file_ids_are_not_silent_successes():
    plugin,_=handler()
    with pytest.raises(ValueError,match='missing'): await plugin.on_finish()
    await plugin.process_buffer(b'owned')
    with pytest.raises(ValueError): await plugin.process_buffer(b'owned')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,mime',[('audio','audio/wav'),('video','video/mp4'),
    ('pdf','application/pdf'),('image','image/png'),('any','application/octet-stream')])
async def test_binary_input_types_preserve_bytes_without_text_decoding(kind,mime):
    plugin,reads=handler(kind,mime)
    await plugin.on_start()
    frames=[frame async for frame in await plugin.process_buffer(b'owned')]
    assert reads==['owned']
    assert b''.join(frame.get('data',b'') for frame in frames)=='Привет'.encode()
    assert not any('text' in frame for frame in frames)
    await plugin.on_finish()
