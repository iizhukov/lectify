"""Exercise freshly generated config helpers without a prepared service checkout."""
import importlib
import sys
from types import SimpleNamespace

import pytest

from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.config import ConfigGenerator
from generators.services.grpc_client import GrpcClientGenerator
from generators.services.logger import LoggerGenerator
from generators.services.scheduler import SchedulerGenerator
from generators.services.settings import SettingsGenerator


def _generated_modules():
    return {name: module for name, module in sys.modules.items()
            if name == "generated" or name.startswith("generated.")}


@pytest.fixture(scope="session")
def generated_flags(tmp_path_factory):
    root = tmp_path_factory.mktemp("feature_flags_service")
    output = root / "generated"
    manifest = ServiceManifest.model_validate({
        "service": {"name": "example_server", "config": {"config_service": "infra_config", "enabled": True}},
    })
    previous_modules = _generated_modules()
    try:
        with pytest.MonkeyPatch.context() as patch:
            # Service generators normally amend sys.path and persist service context.
            # Keep both effects inside this temporary fixture.
            patch.setattr(sys, "path", sys.path.copy())
            patch.setattr(base, "get_settings", lambda: SimpleNamespace(POSTGRES_PORT=5432))
            patch.setattr(base, "get_context_manager", lambda: SimpleNamespace(
                get_service_context=lambda name: ServiceContext(),
            ))
            for generator in (SettingsGenerator, LoggerGenerator, GrpcClientGenerator,
                              SchedulerGenerator, ConfigGenerator):
                generator(manifest, output).generate()
            (output / "__init__.py").write_text("")
            for name in previous_modules:
                sys.modules.pop(name, None)
            importlib.invalidate_caches()
            settings = importlib.import_module("generated.settings")
            settings._settings_instance = settings.Settings(_env_file=None)
            flags = importlib.import_module("generated.config.flags")
            client = importlib.import_module("generated.config.client")
            interceptor = importlib.import_module('generated.config.interceptor')
            feature_flag = flags.feature_flag

            class SampleFeatureFlags(flags.BaseFeatureFlag):
                use_new_logic = feature_flag
                enable_feature_x = feature_flag(default=True)
                custom_timeout: bool = feature_flag(default=False, description="Custom timeout flag")
                standard_flag: bool = True

            result = SimpleNamespace(
                root=root,
                ConfigClient=client.ConfigClient,
                SampleFeatureFlags=SampleFeatureFlags,
                BaseFeatureFlag=flags.BaseFeatureFlag,
                BaseFeatureFlags=flags.BaseFeatureFlags,
                ConfigHandler=interceptor._ConfigProcessingHandler,
            )
    finally:
        # Imported classes retain their module globals. Restore the process import
        # namespace immediately, before another service's tests can import it.
        for name in _generated_modules():
            sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        importlib.invalidate_caches()
    return result


@pytest.fixture(autouse=True)
def clean_flags_cache(generated_flags):
    generated_flags.ConfigClient._flags_cache.clear()
    yield
    generated_flags.ConfigClient._flags_cache.clear()


def test_generated_fixture_does_not_leak_service_imports(generated_flags):
    assert str(generated_flags.root) not in sys.path
    for module in _generated_modules().values():
        assert not str(getattr(module, "__file__", "")).startswith(str(generated_flags.root))


class TestBaseFeatureFlag:
    def test_default_values(self, generated_flags):
        flags = generated_flags.SampleFeatureFlags()
        assert flags.use_new_logic is False
        assert flags.enable_feature_x is True
        assert flags.custom_timeout is False
        assert flags.standard_flag is True

    def test_cached_value_takes_precedence(self, generated_flags):
        # Mock cached flags from infra_config
        generated_flags.ConfigClient._flags_cache["example_server"] = (
            {"use_new_logic": True, "enable_feature_x": False},
            1000.0,
        )

        flags = generated_flags.SampleFeatureFlags(service_name="example_server")
        assert flags.use_new_logic is True
        assert flags.enable_feature_x is False
        # Not in cache -> falls back to default
        assert flags.custom_timeout is False

    def test_local_override_on_instance(self, generated_flags):
        flags = generated_flags.SampleFeatureFlags()
        flags.use_new_logic = True
        assert flags.use_new_logic is True

    def test_get_all_returns_evaluated_dictionary(self, generated_flags):
        generated_flags.ConfigClient._flags_cache["test_svc"] = (
            {"use_new_logic": True},
            1000.0,
        )

        flags = generated_flags.SampleFeatureFlags(service_name="test_svc")
        all_flags = flags.get_all()
        assert isinstance(all_flags, dict)
        assert all_flags["use_new_logic"] is True
        assert all_flags["enable_feature_x"] is True
        assert all_flags["custom_timeout"] is False

    def test_is_enabled_helper(self, generated_flags):
        generated_flags.ConfigClient._flags_cache["test_svc"] = (
            {"use_new_logic": True},
            1000.0,
        )

        flags = generated_flags.SampleFeatureFlags(service_name="test_svc")
        assert flags.is_enabled("use_new_logic") is True
        assert flags.is_enabled("non_existent_flag", default=True) is True
        assert flags.is_enabled("non_existent_flag", default=False) is False

    @pytest.mark.asyncio
    async def test_get_for_user_hook(self, generated_flags):
        flags = generated_flags.SampleFeatureFlags()
        res = await flags.get_for_user("enable_feature_x", user_id="user_999")
        assert res is True

    def test_alias_base_feature_flags(self, generated_flags):
        assert generated_flags.BaseFeatureFlags is generated_flags.BaseFeatureFlag


class TestConfigClientSyncCache:
    def test_sync_cache_hit_and_miss(self, generated_flags):
        generated_flags.ConfigClient._flags_cache["billing"] = (
            {"enable_stripe_v2": True},
            500.0,
        )

        get_flag = generated_flags.ConfigClient.get_cached_flag_sync
        assert get_flag("enable_stripe_v2", service_name="billing") is True
        assert get_flag("unknown_flag", default=False, service_name="billing") is False
        assert get_flag("enable_stripe_v2", default=False, service_name="other_svc") is False


@pytest.mark.asyncio
async def test_config_handler_factories_return_callable_rpc_handlers(generated_flags):
    async def unary(request, context): return request
    async def stream(request, context): yield request
    class Client:
        async def get_feature_flags(self, name): return {'enabled':True}
    class Context:
        def invocation_metadata(self): return [('x-service-name','caller')]
    handler = SimpleNamespace(request_streaming=False,response_streaming=False,
        request_deserializer=None,response_serializer=None,unary_unary=unary,unary_stream=stream,
        stream_unary=unary,stream_stream=stream)
    wrapped = generated_flags.ConfigHandler(handler,SimpleNamespace(invocation_metadata=[]),Client(),'target')
    assert await wrapped.unary_unary('request',Context()) == 'request'
    assert await wrapped.stream_unary('request',Context()) == 'request'
    assert [item async for item in wrapped.unary_stream('request',Context())] == ['request']
    assert [item async for item in wrapped.stream_stream('request',Context())] == ['request']

