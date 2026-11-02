import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import pytest


def handler(**parameters):
    spec = importlib.util.spec_from_file_location('llm_request_business',Path(__file__).parents[1]/'src/plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls=[]
    async def call_llm(**request):
        calls.append(request)
        yield 'Structured '
        yield 'answer'
    values = dict(model='openai/gpt-4o-mini',temperature=.7,max_tokens=100,timeout=5,
                  system_prompt='',user_prompt_template='{{text}}',values={})
    values.update(parameters)
    sidecar = SimpleNamespace(call_llm=call_llm,save_artifact=AsyncMock())
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(**values)),sidecar),calls


@pytest.mark.asyncio
async def test_joined_prompt_and_text_render_once_then_save_actual_answer():
    plugin,calls = handler(values={'name':'Alice'})
    await plugin.on_start()
    await plugin.process_input('prompt',json.dumps({'system_prompt':'For {{name}}',
        'user_prompt_template':'{{transcript}}'}).encode())
    await plugin.process_input('text',b'hello {{name}}')
    assert calls == []
    result = await plugin.on_finish()
    assert result == {'response':b'Structured answer'}
    assert calls[0]['messages'] == [{'role':'system','content':'For Alice'},
                                  {'role':'user','content':'hello {{name}}'}]
    assert calls[0]['max_tokens']==100 and calls[0]['purpose']=='llm_request'
    assert plugin.sidecar.save_artifact.call_args.kwargs['data'] == b'Structured answer'


@pytest.mark.asyncio
async def test_missing_variables_and_invalid_limits_do_not_call_provider():
    plugin,calls=handler(user_prompt_template='{{missing}}')
    await plugin.on_start()
    with pytest.raises(ValueError,match='variable'): await plugin.on_finish()
    assert calls==[]
    for parameters in ({'max_tokens':0},{'timeout':301},{'temperature':float('nan')},{'values':{'a':1}}):
        plugin,calls=handler(**parameters)
        with pytest.raises(ValueError): await plugin.on_start()
        assert calls==[]


@pytest.mark.asyncio
async def test_empty_provider_response_is_not_a_successful_artifact():
    plugin,_=handler()
    async def empty(**request):
        if False: yield ''
    plugin.sidecar.call_llm=empty
    await plugin.on_start()
    with pytest.raises(ValueError,match='empty'): await plugin.on_finish()
    plugin.sidecar.save_artifact.assert_not_called()
