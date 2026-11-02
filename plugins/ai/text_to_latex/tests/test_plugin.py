import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

DOCUMENT=r'\documentclass{article}\begin{document}Notes\end{document}'


def handler(subject='auto',classification='math'):
    spec=importlib.util.spec_from_file_location('latex_generation',Path(__file__).parents[1]/'src/plugin.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    calls=[]
    async def call_llm(**request):
        calls.append(request)
        yield classification if request['purpose']=='subject' else '```latex\n'+DOCUMENT+'\n```'
    params=SimpleNamespace(subject=subject,segments=3,model='openai/gpt-4o-mini',max_tokens=4096,timeout=5,values={})
    sidecar=SimpleNamespace(call_llm=call_llm,log=AsyncMock(),save_artifact=AsyncMock())
    return module.PluginHandler(SimpleNamespace(parameters=params),sidecar),calls


@pytest.mark.asyncio
async def test_subject_detection_fence_removal_and_real_generation_result():
    plugin,calls=handler()
    await plugin.on_start(); await plugin.process_input('text',b'Lecture text')
    result=await plugin.on_finish()
    assert [call['purpose'] for call in calls]==['subject','latex']
    assert result['latex']==DOCUMENT.encode()
    assert json.loads(result['metadata'])=={'subject':'math','segments':3}
    assert plugin.sidecar.save_artifact.call_args.kwargs['data']==DOCUMENT.encode()


@pytest.mark.asyncio
async def test_unknown_subject_falls_back_and_explicit_subject_avoids_classifier():
    plugin,_=handler(classification='not-a-subject')
    await plugin.on_start(); await plugin.process_input('text',b'Lecture')
    assert json.loads((await plugin.on_finish())['metadata'])['subject']=='sys_prompt'
    plugin,calls=handler(subject='physics')
    await plugin.on_start(); await plugin.process_input('text',b'Lecture')
    await plugin.on_finish()
    assert [call['purpose'] for call in calls]==['latex']


@pytest.mark.asyncio
async def test_empty_source_never_calls_model_or_saves_artifact():
    plugin,calls=handler()
    await plugin.on_start()
    with pytest.raises(ValueError,match='empty'): await plugin.on_finish()
    assert calls==[]
    plugin.sidecar.save_artifact.assert_not_called()
