import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest


def handler(**overrides):
    spec=importlib.util.spec_from_file_location('markdown_llm_business',Path(__file__).parents[1]/'src/plugin.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    parameters=dict(max_chars=40000,style='detailed',model='openai/gpt-4o-mini',temperature=.7,
        max_tokens=4096,timeout=5,values={})
    parameters.update(overrides)
    calls=[]
    async def call_llm(**request):
        calls.append(request)
        yield '# Generated\n'
        yield 'Actual summary'
    sidecar=SimpleNamespace(call_llm=call_llm,save_artifact=AsyncMock())
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(**parameters)),sidecar),calls


@pytest.mark.asyncio
async def test_monolith_behavior_calls_llm_and_saves_actual_content():
    plugin,calls=handler(max_chars=5,style='brief')
    await plugin.on_start()
    await plugin.process_input('text','Привет длинный текст'.encode())
    result=await plugin.on_finish()
    assert calls[0]['purpose']=='summary'
    assert calls[0]['messages'][1]['content']=='Приве'
    assert 'краткий' in calls[0]['messages'][0]['content']
    assert result['md_stream']==b'# Generated\nActual summary'
    assert json.loads(result['metadata'])['char_count']==len('# Generated\nActual summary')
    assert plugin.sidecar.save_artifact.call_args.kwargs['data']==result['md_stream']


@pytest.mark.asyncio
async def test_library_prompt_and_values_are_rendered_in_one_pass():
    plugin,calls=handler(values={'name':'Alice'})
    await plugin.on_start()
    await plugin.process_input('text',b'{{name}} stays literal')
    await plugin.process_input('prompt',json.dumps({'system_prompt':'For {{name}}',
        'user_prompt_template':'Notes: {{transcript}}'}).encode())
    await plugin.on_finish()
    assert calls[0]['messages']==[{'role':'system','content':'For Alice'},
        {'role':'user','content':'Notes: {{name}} stays literal'}]


@pytest.mark.asyncio
async def test_invalid_or_empty_input_never_calls_provider():
    for overrides in ({'style':'unknown'},{'max_chars':0},{'temperature':float('inf')}):
        plugin,calls=handler(**overrides)
        with pytest.raises(ValueError): await plugin.on_start()
        assert not calls
    plugin,calls=handler()
    await plugin.on_start()
    with pytest.raises(ValueError,match='empty'): await plugin.on_finish()
    assert not calls
