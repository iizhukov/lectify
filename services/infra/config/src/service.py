import grpc

from datetime import datetime, timezone
from sqlalchemy import select


from generated.protos.server.index_pb2 import (
    GetFeatureFlagsRequest,
    GetFeatureFlagsResponse,
    SetFeatureFlagRequest,
    SetFeatureFlagResponse,
    GetConfigurationRequest,
    GetConfigurationResponse,
)
from generated.grpc_server.grpc_app import ConfigServiceBase
from generated.logger import get_logger
from generated.db.connection import get_session_factory

from src.models import FeatureFlag


log = get_logger("service")


class ConfigServiceImpl(ConfigServiceBase):
    async def GetFeatureFlags(self, request: GetFeatureFlagsRequest, context):
        service_name = request.service_name or ""
        factory = get_session_factory()

        async with factory() as session:
            result = await session.execute(
                select(FeatureFlag.flag_name, FeatureFlag.enabled, FeatureFlag.updated_at)
                .where(FeatureFlag.service_name == service_name)
                .order_by(FeatureFlag.flag_name)
            )
            rows = result.all()

        flags = {row.flag_name: row.enabled for row in rows}
        updated_at = max((int(row.updated_at.timestamp()) for row in rows), default=0)

        log.info(
            "feature_flags_served",
            service=service_name,
            count=len(flags),
            updated_at=updated_at,
        )
        return GetFeatureFlagsResponse(flags=flags, updated_at=updated_at)

    async def SetFeatureFlag(self, request: SetFeatureFlagRequest, context):
        service_name = request.service_name or ""
        flag_name = request.flag_name or ""
        enabled = request.enabled
        now = datetime.now(timezone.utc)

        if not service_name or not flag_name:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "service_name and flag_name are required")

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(FeatureFlag)
                .where(
                    FeatureFlag.service_name == service_name,
                    FeatureFlag.flag_name == flag_name,
                )
            )
            flag = result.scalar_one_or_none()

            if flag:
                flag.enabled = enabled
                flag.updated_at = now
            else:
                flag = FeatureFlag(
                    service_name=service_name,
                    flag_name=flag_name,
                    enabled=enabled,
                    updated_at=now,
                )
                session.add(flag)

            await session.commit()
            await session.refresh(flag)

        updated_at_ts = int(now.timestamp())
        log.info(
            "feature_flag_set",
            service=service_name,
            flag=flag_name,
            enabled=enabled,
            updated_at=updated_at_ts,
        )
        return SetFeatureFlagResponse(
            success=True,
            service_name=service_name,
            flag_name=flag_name,
            enabled=enabled,
            updated_at=updated_at_ts,
        )

    async def GetConfiguration(self, request: GetConfigurationRequest, context):
        service_name = request.service_name or ""
        factory = get_session_factory()

        async with factory() as session:
            result = await session.execute(
                select(FeatureFlag.flag_name, FeatureFlag.enabled)
                .where(FeatureFlag.service_name == service_name)
                .order_by(FeatureFlag.flag_name)
            )
            rows = result.all()

        values = {row.flag_name: "true" if row.enabled else "false" for row in rows}

        log.info(
            "config_served",
            service=service_name,
            config_type=request.config_type or "",
            count=len(values),
        )
        return GetConfigurationResponse(values=values, updated_at=int(datetime.now(timezone.utc).timestamp()))
