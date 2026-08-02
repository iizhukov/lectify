import time
import grpc

import generated.protos.server.index_pb2 as index_pb2
from generated.grpc_server.grpc_app import ExampleServiceBase
from generated.logger import get_logger
from generated.db.connection import get_session_factory

from src.metrics import USERS_CREATED, USER_CREATION_DURATION
from src.models import User


log = get_logger("service")


class ExampleServiceImpl(ExampleServiceBase):
    async def Ping(self, request, context):
        log.info("ping", message=request.message)

        return index_pb2.PingResponse(
            message=f"pong: {request.message}",
            timestamp=int(time.time()),
        )

    async def CreateUser(self, request, context):
        start = time.monotonic()
        log.info("create_user", username=request.username)

        factory = get_session_factory()
        async with factory() as session:
            user = User(
                username=request.username,
                email=request.email,
                full_name=request.full_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        duration = time.monotonic() - start
        USERS_CREATED.add(1)
        USER_CREATION_DURATION.record(duration)

        return index_pb2.UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
        )

    async def GetUser(self, request, context):
        log.info("get_user", id=request.id)

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select
            result = await session.execute(select(User).where(User.id == request.id))
            user = result.scalar_one_or_none()

        if not user:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"User {request.id} not found")

        return index_pb2.UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
        )
