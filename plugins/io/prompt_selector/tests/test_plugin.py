import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import pytest


@pytest.mark.asyncio
async def test_selection_preserves_unrendered_template_and_declared_variables():
    spec=importlib.util.spec_from_file_location('selector_business',Path(__file__).parents[1]/'src/plugin.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prompt=dict(prompt_id='owned',system_prompt='Summarize',user_prompt_template='{{transcript}}',
                rendered_user_prompt='',variables=['transcript'])
    sidecar=SimpleNamespace(fetch_prompt=AsyncMock(return_value=prompt))
    plugin=module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(prompt_id='owned')),sidecar)
    assert json.loads((await plugin.on_start())['prompt'])==prompt
    sidecar.fetch_prompt.assert_awaited_once_with('owned',raw_template=True)
