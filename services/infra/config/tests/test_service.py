import pytest
import grpc
from datetime import datetime, timezone
from sqlalchemy import select

import generated.protos.server.index_pb2 as pb2
from generated.testing.context import MockRpcError
from src.service import ConfigServiceImpl
from src.models import FeatureFlag


@pytest.mark.asyncio
async def test_get_feature_flags_empty(test_session, mock_context):
    servicer = ConfigServiceImpl()
    req = pb2.GetFeatureFlagsRequest(service_name="non_existent_service")

    resp = await servicer.GetFeatureFlags(req, mock_context)

    assert len(resp.flags) == 0
    assert resp.updated_at == 0
    assert mock_context.code == grpc.StatusCode.OK


@pytest.mark.asyncio
async def test_set_feature_flag_create(test_session, mock_context):
    servicer = ConfigServiceImpl()
    req = pb2.SetFeatureFlagRequest(
        service_name="example_server",
        flag_name="use_new_logic",
        enabled=True,
    )

    resp = await servicer.SetFeatureFlag(req, mock_context)

    assert resp.success is True
    assert resp.service_name == "example_server"
    assert resp.flag_name == "use_new_logic"
    assert resp.enabled is True
    assert resp.updated_at > 0

    # Verify persisted in database
    stmt = select(FeatureFlag).where(
        FeatureFlag.service_name == "example_server",
        FeatureFlag.flag_name == "use_new_logic",
    )
    flag_in_db = (await test_session.execute(stmt)).scalar_one_or_none()
    assert flag_in_db is not None
    assert flag_in_db.enabled is True


@pytest.mark.asyncio
async def test_set_feature_flag_update(test_session, mock_context):
    servicer = ConfigServiceImpl()

    # 1. Create flag with enabled=True
    await servicer.SetFeatureFlag(
        pb2.SetFeatureFlagRequest(
            service_name="example_server",
            flag_name="beta_feature",
            enabled=True,
        ),
        mock_context,
    )

    # 2. Update flag with enabled=False
    resp = await servicer.SetFeatureFlag(
        pb2.SetFeatureFlagRequest(
            service_name="example_server",
            flag_name="beta_feature",
            enabled=False,
        ),
        mock_context,
    )

    assert resp.success is True
    assert resp.enabled is False

    # Verify update in database
    stmt = select(FeatureFlag).where(
        FeatureFlag.service_name == "example_server",
        FeatureFlag.flag_name == "beta_feature",
    )
    flag_in_db = (await test_session.execute(stmt)).scalar_one_or_none()
    assert flag_in_db is not None
    assert flag_in_db.enabled is False


@pytest.mark.asyncio
async def test_set_feature_flag_validation_missing_service_or_flag(test_session, mock_context):
    servicer = ConfigServiceImpl()

    # Missing flag_name
    with pytest.raises(MockRpcError) as exc_info:
        await servicer.SetFeatureFlag(
            pb2.SetFeatureFlagRequest(service_name="example_server", flag_name=""),
            mock_context,
        )
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "service_name and flag_name are required" in exc_info.value.details()

    # Missing service_name
    mock_context_2 = mock_context.__class__()
    with pytest.raises(MockRpcError) as exc_info2:
        await servicer.SetFeatureFlag(
            pb2.SetFeatureFlagRequest(service_name="", flag_name="my_flag"),
            mock_context_2,
        )
    assert exc_info2.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_get_feature_flags_isolation_between_services(test_session, mock_context):
    servicer = ConfigServiceImpl()

    # Seed flags for service_a and service_b
    await servicer.SetFeatureFlag(
        pb2.SetFeatureFlagRequest(service_name="service_a", flag_name="flag_1", enabled=True),
        mock_context,
    )
    await servicer.SetFeatureFlag(
        pb2.SetFeatureFlagRequest(service_name="service_a", flag_name="flag_2", enabled=False),
        mock_context,
    )
    await servicer.SetFeatureFlag(
        pb2.SetFeatureFlagRequest(service_name="service_b", flag_name="flag_3", enabled=True),
        mock_context,
    )

    # Query service_a
    resp_a = await servicer.GetFeatureFlags(
        pb2.GetFeatureFlagsRequest(service_name="service_a"),
        mock_context,
    )
    assert len(resp_a.flags) == 2
    assert resp_a.flags["flag_1"] is True
    assert resp_a.flags["flag_2"] is False
    assert "flag_3" not in resp_a.flags

    # Query service_b
    resp_b = await servicer.GetFeatureFlags(
        pb2.GetFeatureFlagsRequest(service_name="service_b"),
        mock_context,
    )
    assert len(resp_b.flags) == 1
    assert resp_b.flags["flag_3"] is True


@pytest.mark.asyncio
async def test_get_configuration(test_session, mock_context):
    servicer = ConfigServiceImpl()

    await servicer.SetFeatureFlag(
        pb2.SetFeatureFlagRequest(service_name="config_test_svc", flag_name="opt_in", enabled=True),
        mock_context,
    )
    await servicer.SetFeatureFlag(
        pb2.SetFeatureFlagRequest(service_name="config_test_svc", flag_name="opt_out", enabled=False),
        mock_context,
    )

    resp = await servicer.GetConfiguration(
        pb2.GetConfigurationRequest(service_name="config_test_svc", config_type="features"),
        mock_context,
    )

    assert len(resp.values) == 2
    assert resp.values["opt_in"] == "true"
    assert resp.values["opt_out"] == "false"
    assert resp.updated_at > 0

