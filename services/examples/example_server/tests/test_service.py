import pytest
import grpc
from sqlalchemy import select

import generated.protos.server.index_pb2 as pb2
from generated.testing.context import MockRpcError
from src.service import ExampleServiceImpl
from src.models import User


@pytest.mark.asyncio
async def test_ping_default_flag(mock_context):
    servicer = ExampleServiceImpl()
    request = pb2.PingRequest(message="test message")

    response = await servicer.Ping(request, mock_context)

    assert response.message == "pong: test message"
    assert response.timestamp > 0
    assert mock_context.code == grpc.StatusCode.OK


@pytest.mark.asyncio
async def test_ping_with_new_logic_flag(mock_context, mock_feature_flags):
    mock_feature_flags({"use_new_logic": True})

    servicer = ExampleServiceImpl()
    request = pb2.PingRequest(message="test message")

    response = await servicer.Ping(request, mock_context)

    assert response.message == "[NEW LOGIC] pong: test message"
    assert response.timestamp > 0
    assert mock_context.code == grpc.StatusCode.OK


@pytest.mark.asyncio
async def test_create_and_get_user(test_session, mock_context):
    servicer = ExampleServiceImpl()

    # 1. Create a user
    create_req = pb2.CreateUserRequest(
        username="johndoe",
        email="john@example.com",
        full_name="John Doe",
    )
    create_resp = await servicer.CreateUser(create_req, mock_context)

    assert create_resp.id > 0
    assert create_resp.username == "johndoe"
    assert create_resp.email == "john@example.com"
    assert create_resp.full_name == "John Doe"
    assert create_resp.is_active is True

    # 2. Get the user
    get_req = pb2.GetUserRequest(id=create_resp.id)
    get_resp = await servicer.GetUser(get_req, mock_context)

    assert get_resp.id == create_resp.id
    assert get_resp.username == "johndoe"
    assert get_resp.email == "john@example.com"

    # 3. Direct verification in test_session
    stmt = select(User).where(User.id == create_resp.id)
    user_in_db = (await test_session.execute(stmt)).scalar_one_or_none()
    assert user_in_db is not None
    assert user_in_db.email == "john@example.com"


@pytest.mark.asyncio
async def test_get_user_not_found(test_session, mock_context):
    servicer = ExampleServiceImpl()
    get_req = pb2.GetUserRequest(id=99999)

    with pytest.raises(MockRpcError) as exc_info:
        await servicer.GetUser(get_req, mock_context)

    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND
    assert "User 99999 not found" in exc_info.value.details()
    assert mock_context.code == grpc.StatusCode.NOT_FOUND
    assert mock_context.is_aborted is True

