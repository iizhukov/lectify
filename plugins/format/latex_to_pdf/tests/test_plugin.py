import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

DOCUMENT=r'\documentclass{article}\begin{document}Real PDF text\end{document}'


def handler(**overrides):
    spec=importlib.util.spec_from_file_location('pdf_business',Path(__file__).parents[1]/'src/plugin.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    values=dict(max_attempts=3,use_llm_repair=True,model='openai/gpt-4o-mini',compile_timeout=10,repair_timeout=5)
    values.update(overrides)
    calls=[]
    async def repair(**request): calls.append(request); yield '```latex\n'+DOCUMENT+'\n```'
    sidecar=SimpleNamespace(call_llm=repair,save_artifact=AsyncMock())
    return module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(**values)),sidecar),calls


@pytest.mark.asyncio
async def test_real_compiler_and_actual_pdf_when_available():
    if not shutil.which('pdflatex'): pytest.skip('Real pdflatex required; Docker scenarios exercise it')
    plugin,calls=handler()
    await plugin.on_start(); await plugin.process_buffer(DOCUMENT.encode())
    result=await plugin.on_finish()
    assert result['pdf'].startswith(b'%PDF-') and len(result['pdf'])>1000
    assert json.loads(result['metadata'])=={'attempts':1}
    assert not calls


@pytest.mark.asyncio
async def test_compiler_failure_triggers_bounded_repair_and_saves_only_success(monkeypatch):
    plugin,calls=handler()
    attempts=[]
    async def compile(directory):
        source=(directory/'document.tex').read_text(); attempts.append(source)
        if len(attempts)==1:
            (directory/'compile.log').write_text('Undefined control sequence')
            return False
        assert source==DOCUMENT
        (directory/'document.pdf').write_bytes(b'%PDF-TEST')
        return True
    monkeypatch.setattr(plugin,'compile',compile)
    await plugin.on_start(); await plugin.process_buffer(b'broken LaTeX')
    result=await plugin.on_finish()
    assert len(attempts)==2 and len(calls)==1 and calls[0]['purpose']=='latex_repair'
    assert json.loads(result['metadata'])['attempts']==2


@pytest.mark.asyncio
async def test_failed_compilation_without_repair_never_saves_success(monkeypatch):
    plugin,calls=handler(use_llm_repair=False)
    monkeypatch.setattr(plugin,'compile',AsyncMock(return_value=False))
    await plugin.on_start(); await plugin.process_buffer(b'broken')
    with pytest.raises(ValueError,match='compilation failed'): await plugin.on_finish()
    assert not calls
    plugin.sidecar.save_artifact.assert_not_called()


@pytest.mark.asyncio
async def test_repair_stops_at_configured_total_compile_attempts(monkeypatch):
    plugin,calls=handler(max_attempts=2)
    attempts=[]
    async def compile(directory):
        attempts.append(True)
        (directory/'compile.log').write_text('Compilation still fails')
        return False
    monkeypatch.setattr(plugin,'compile',compile)
    await plugin.on_start(); await plugin.process_buffer(b'broken')
    with pytest.raises(ValueError,match='attempt limit'): await plugin.on_finish()
    assert len(attempts)==2 and len(calls)==1
    plugin.sidecar.save_artifact.assert_not_called()
