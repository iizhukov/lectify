import pytest
from src.policy.models import PermissionRule, PermissionEffect
from src.policy.store import PermissionStore
from src.policy.loader import load_default_rules, _parse_service_yaml


def test_permission_effect_proto_conversion():
    assert PermissionEffect.from_proto(0) == PermissionEffect.DENY
    assert PermissionEffect.from_proto(1) == PermissionEffect.ALLOW
    assert PermissionEffect.from_proto(2) == PermissionEffect.DENY

    assert PermissionEffect.ALLOW.to_proto() == 1
    assert PermissionEffect.DENY.to_proto() == 2


def test_permission_rule_dataclass():
    rule = PermissionRule(
        source_service="client",
        target_service="server",
        effect=PermissionEffect.ALLOW,
        description="test",
        is_default=True,
    )
    assert rule.source_service == "client"
    assert rule.target_service == "server"
    assert rule.effect == PermissionEffect.ALLOW
    assert rule.is_default is True

    custom_rule = PermissionRule(
        source_service="client",
        target_service="server",
        effect=PermissionEffect.DENY,
        description="test",
        is_default=False,
    )
    assert custom_rule.effect == PermissionEffect.DENY
    assert custom_rule.is_default is False


@pytest.mark.asyncio
async def test_permission_store_in_memory_operations(test_session):
    store = PermissionStore()

    # Rule does not exist initially
    assert await store.check_permission("svc_a", "svc_b") is False
    allowed, effect = await store.check_permission_full("svc_a", "svc_b")
    assert allowed is False
    assert effect is None

    # Set ALLOW rule
    await store.set_rule("svc_a", "svc_b", PermissionEffect.ALLOW, description="allow rule")
    assert await store.check_permission("svc_a", "svc_b") is True
    allowed, effect = await store.check_permission_full("svc_a", "svc_b")
    assert allowed is True
    assert effect == PermissionEffect.ALLOW

    # Set DENY rule (override)
    await store.set_rule("svc_a", "svc_b", PermissionEffect.DENY)
    assert await store.check_permission("svc_a", "svc_b") is False
    allowed, effect = await store.check_permission_full("svc_a", "svc_b")
    assert allowed is False
    assert effect == PermissionEffect.DENY

    # List rules
    rules = store.list_rules()
    assert len(rules) == 1
    assert rules[0].source_service == "svc_a"

    # Remove rule
    removed = await store.remove_rule("svc_a", "svc_b")
    assert removed is True
    assert await store.check_permission("svc_a", "svc_b") is False

    # Remove non-existent rule
    removed_again = await store.remove_rule("svc_a", "svc_b")
    assert removed_again is False


def test_parse_service_yaml(tmp_path):
    yaml_content = """\
service:
  name: test_api
  ticket_auth:
    enabled: true
    tas_service: infra_tas
  config:
    enabled: true
  grpc_client:
    enabled: true
    services:
      - service_alpha
      - service_beta
"""
    yaml_file = tmp_path / "service.yaml"
    yaml_file.write_text(yaml_content)

    res = _parse_service_yaml(yaml_file)
    assert res is not None
    source_name, targets = res

    assert source_name == "test_api"
    target_set = set(targets)
    assert "infra_tas" in target_set
    assert "infra_config" in target_set
    assert "service_alpha" in target_set
    assert "service_beta" in target_set

