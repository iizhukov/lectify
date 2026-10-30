"""Generated S3 adapter behaviour without an object-store or credentials."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.s3 import S3Generator
from generators.services.requirements import _base_requirements


SCENARIO = r'''
from types import SimpleNamespace
import boto3

calls = []
class Response:
    closed = False
    fail = False
    def read(self, size=-1):
        if self.fail:
            raise RuntimeError('read failure')
        return b'payload'
    def close(self):
        self.closed = True

class Client:
    response = Response()
    def put_object(self, **request):
        calls.append(('put', request))
    def get_object(self, **request):
        calls.append(('get', request))
        return {'Body': self.response}
    def delete_object(self, **request):
        calls.append(('delete', request))

client = Client()
def factory(service, **options):
    assert service == 's3'
    config = options['config']
    assert config.connect_timeout == 5 and config.read_timeout == 30
    assert config.retries['total_max_attempts'] == 2
    return client
boto3.client = factory
from generated.s3.s3 import get_user_files_client
adapter = get_user_files_client()
class GuardBody:
    def read(self, *args):
        raise AssertionError('Adapter must not materialize upload body')
body = GuardBody()
adapter.put_stream('opaque-id', body, 'text/plain')
assert calls[-1] == ('put', {'Bucket': 'user-files', 'Key': 'opaque-id', 'Body': body, 'ContentType': 'text/plain'})
response = adapter.open('opaque-id')
assert response is client.response and not response.closed
assert response.read(65536) == b'payload'
response.close()
adapter.delete('opaque-id')
assert calls[-1] == ('delete', {'Bucket': 'user-files', 'Key': 'opaque-id'})
client.response = Response()
assert adapter.get('opaque-id') == b'payload' and client.response.closed
client.response = Response()
client.response.fail = True
try:
    adapter.get('opaque-id')
except RuntimeError:
    pass
else:
    raise AssertionError('Read failure must propagate')
assert client.response.closed
'''


def test_generated_s3_adapter(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(base, 'get_settings', lambda: SimpleNamespace(POSTGRES_PORT=5432))
    monkeypatch.setattr(base, 'get_context_manager', lambda: SimpleNamespace(
        get_service_context=lambda name: ServiceContext()))
    manifest = ServiceManifest.model_validate({'service': {'name': 'storage_test',
        'minio': {'enabled': True, 'buckets': ['user-files']}}})
    S3Generator(manifest, tmp_path / 'generated').generate()
    # Replace configuration only: execute the generated adapter against fake boto calls.
    (tmp_path / 'generated/settings.py').write_text(
        'from types import SimpleNamespace\n'
        'def get_settings():\n'
        '    return SimpleNamespace(minio=SimpleNamespace(endpoint="localhost:9000", access_key="test", secret_key="test"))\n')
    (tmp_path / 'generated/logger.py').write_text('def get_logger(name): return None\n')
    result = subprocess.run([sys.executable, '-c', SCENARIO], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path)), capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert any(item.startswith('boto3') for item in _base_requirements(manifest.service))
