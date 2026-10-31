import json
from types import SimpleNamespace
import grpc
import pytest
from sqlalchemy import select,func
from generated.testing.context import MockRpcError,MockServicerContext
from generated.protos.server import index_pb2 as pb
from src.models import PluginRegistryModel
from src.service import OrchestratorServiceImpl


def context(admin=False):
    value = MockServicerContext()
    value.lectify_principal = SimpleNamespace(user_id='admin',is_admin=admin)
    return value


def request(manifest):
    return pb.RegisterPluginManifestRequest(plugin_id='plugin',version='0.1.0',manifest_yaml=manifest)


@pytest.mark.asyncio
async def test_registered_version_is_semantically_idempotent_and_immutable(test_session):
    service = OrchestratorServiceImpl()
    original = 'plugin:\n  name: plugin\n  version: 0.1.0\n'
    assert (await service.RegisterPluginManifest(request(original),context(admin=True))).success
    same = json.dumps({'plugin':{'version':'0.1.0','name':'plugin'}})
    assert (await service.RegisterPluginManifest(request(same),context(admin=True))).success
    changed = original + '  permissions:\n    storage:\n      enabled: true\n'
    with pytest.raises(MockRpcError) as error:
        await service.RegisterPluginManifest(request(changed),context(admin=True))
    assert error.value.code() == grpc.StatusCode.ALREADY_EXISTS
    row = await test_session.get(PluginRegistryModel,('plugin','0.1.0'))
    assert json.loads(row.manifest_yaml)['plugin']['permissions']['storage']['enabled'] is False
    assert await test_session.scalar(select(func.count()).select_from(PluginRegistryModel)) == 1


@pytest.mark.asyncio
async def test_invalid_manifest_never_enters_registry(test_session):
    service = OrchestratorServiceImpl()
    for raw in ('plugin: {name: other}', 'plugin: {name: plugin, name: other}',
                'plugin: &p {name: plugin}\ncopy: *p',
                'plugin: {name: plugin, version: "2"}',
                'plugin: {name: plugin, outputs: [{name: out}, {name: out}]}',
                'plugin: {name: plugin, parameters: [{name: x, type: float, default: .nan}]}',
                json.dumps({'plugin':{'name':'plugin','category':'x'*65}}),
                json.dumps({'plugin':{'name':'plugin','description':'bad\x00text'}}),
                json.dumps({'plugin':{'name':'plugin','description':'bad\ud800text'}})):
        with pytest.raises(MockRpcError) as error:
            await service.RegisterPluginManifest(request(raw),context(admin=True))
        assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert await test_session.scalar(select(func.count()).select_from(PluginRegistryModel)) == 0
