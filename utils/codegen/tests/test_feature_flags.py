import sys
import pytest

from pathlib import Path


codegen_dir = Path(__file__).resolve().parent.parent
repo_root = codegen_dir.parent.parent
server_root = repo_root / "services" / "examples" / "example_server"

if str(server_root) not in sys.path:
    sys.path.insert(0, str(server_root))

from generated.config.flags import (
    BaseFeatureFlag,
    BaseFeatureFlags,
    feature_flag,
    FeatureFlagField,
)
from generated.config.client import ConfigClient


@pytest.fixture(autouse=True)
def clean_flags_cache():
    ConfigClient._flags_cache.clear()
    yield
    ConfigClient._flags_cache.clear()


class SampleFeatureFlags(BaseFeatureFlag):
    use_new_logic = feature_flag
    enable_feature_x = feature_flag(default=True)
    custom_timeout: bool = feature_flag(default=False, description="Custom timeout flag")
    standard_flag: bool = True


class TestBaseFeatureFlag:
    def test_default_values(self):
        flags = SampleFeatureFlags()
        assert flags.use_new_logic is False
        assert flags.enable_feature_x is True
        assert flags.custom_timeout is False
        assert flags.standard_flag is True

    def test_cached_value_takes_precedence(self):
        ConfigClient._flags_cache["example_server"] = (
            {"use_new_logic": True, "enable_feature_x": False},
            1000.0,
        )

        flags = SampleFeatureFlags(service_name="example_server")
        assert flags.use_new_logic is True
        assert flags.enable_feature_x is False
        assert flags.custom_timeout is False

    def test_local_override_on_instance(self):
        flags = SampleFeatureFlags()
        flags.use_new_logic = True
        assert flags.use_new_logic is True

    def test_get_all_returns_evaluated_dictionary(self):
        ConfigClient._flags_cache["test_svc"] = (
            {"use_new_logic": True},
            1000.0,
        )

        flags = SampleFeatureFlags(service_name="test_svc")
        all_flags = flags.get_all()
        assert isinstance(all_flags, dict)
        assert all_flags["use_new_logic"] is True
        assert all_flags["enable_feature_x"] is True
        assert all_flags["custom_timeout"] is False

    def test_is_enabled_helper(self):
        ConfigClient._flags_cache["test_svc"] = (
            {"use_new_logic": True},
            1000.0,
        )

        flags = SampleFeatureFlags(service_name="test_svc")
        assert flags.is_enabled("use_new_logic") is True
        assert flags.is_enabled("non_existent_flag", default=True) is True
        assert flags.is_enabled("non_existent_flag", default=False) is False

    @pytest.mark.asyncio
    async def test_get_for_user_hook(self):
        flags = SampleFeatureFlags()
        res = await flags.get_for_user("enable_feature_x", user_id="user_999")
        assert res is True

    def test_alias_base_feature_flags(self):
        assert BaseFeatureFlags is BaseFeatureFlag


class TestConfigClientSyncCache:
    def test_sync_cache_hit_and_miss(self):
        ConfigClient._flags_cache["billing"] = (
            {"enable_stripe_v2": True},
            500.0,
        )

        assert ConfigClient.get_cached_flag_sync("enable_stripe_v2", service_name="billing") is True
        assert ConfigClient.get_cached_flag_sync("unknown_flag", default=False, service_name="billing") is False
        assert ConfigClient.get_cached_flag_sync("enable_stripe_v2", default=False, service_name="other_svc") is False
