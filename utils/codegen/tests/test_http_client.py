"""Fresh generated HTTP/settings execution, no external services or credentials."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from config.models import HttpConfig, ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.http import HttpGenerator
from generators.services.logger import LoggerGenerator
from generators.services.main import MainGenerator
from generators.services.settings import SettingsGenerator


SCENARIO = r'''
import asyncio
import json
import os
import threading
from generated import settings as settings_module
from generated.http.client import get_http_client, close_http_client, run_blocking

settings = settings_module.get_settings()
assert settings.extensions == {'business': {'flag': True, 'optional': None, 'text': '"quoted"'}}
os.environ['HTTP_TEST_EXTENSIONS'] = json.dumps({'business': {'flag': False}})
os.environ['HTTP_TEST_HTTP_BEARER_TOKEN'] = 'test-only-sensitive-value'
settings_module._settings_instance = None
settings = settings_module.get_settings()
assert settings.extensions == {'business': {'flag': False}}
assert 'test-only-sensitive-value' not in repr(settings) and 'test-only-sensitive-value' not in repr(settings.http)
assert settings.http.bearer_token.get_secret_value() == 'test-only-sensitive-value'

async def main():
    client = get_http_client()
    assert get_http_client() is client
    await close_http_client()
    assert client.is_closed
    replacement = get_http_client()
    assert replacement is not client
    await close_http_client()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def worker():
        started.set()
        assert release.wait(2)
        finished.set()
    task = asyncio.create_task(run_blocking(worker))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError('Cancellation was swallowed')
    assert finished.is_set()

asyncio.run(main())
'''


def test_http_settings_pool_cleanup_and_cancellation(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(base, 'get_settings', lambda: SimpleNamespace(POSTGRES_PORT=5432))
    monkeypatch.setattr(base, 'get_context_manager', lambda: SimpleNamespace(
        get_service_context=lambda name: ServiceContext()))
    manifest = ServiceManifest.model_validate({'service': {'name': 'http_test', 'http': {'enabled': True}},
        'extensions': {'business': {'flag': True, 'optional': None, 'text': '"quoted"'}}})
    (tmp_path / 'service.yaml').write_text('service:\n  name: http_test\n')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/__init__.py').touch()
    for generator in (SettingsGenerator, LoggerGenerator, HttpGenerator):
        generator(manifest, tmp_path / 'generated').generate()
    main = MainGenerator(manifest, tmp_path / 'generated').render('services/main/main.py.j2')
    compile(main, 'main.py', 'exec')
    assert 'await close_http_client()' in main
    result = subprocess.run([sys.executable, '-c', SCENARIO], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path)), capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), 601])
def test_http_timeout_is_finite_and_bounded(value):
    with pytest.raises(ValidationError):
        HttpConfig(timeout_seconds=value)
