import time
import pytest
import grpc
from sqlalchemy import select

import generated.protos.server.index_pb2 as pb2
from src.service import TicketServiceImpl, _encode_jwt, _decode_jwt
from src.policy.store import get_permission_store, reset_permission_store
from src.policy.models import PermissionEffect
from src.models import RevokedTicket, PermissionRuleModel
from generated.testing.context import MockRpcError


@pytest.fixture(autouse=True)
def reset_tas_store():
    reset_permission_store()
    yield
    reset_permission_store()


@pytest.mark.asyncio
async def test_get_public_key(mock_context):
    servicer = TicketServiceImpl()
    resp = await servicer.GetPublicKey(pb2.GetPublicKeyRequest(), mock_context)

    assert resp.algorithm == "RS256"
    assert "-----BEGIN PUBLIC KEY-----" in resp.public_key
    assert "-----END PUBLIC KEY-----" in resp.public_key
    assert mock_context.code == grpc.StatusCode.OK


@pytest.mark.asyncio
async def test_issue_ticket_allowed_and_denied(test_session, mock_context):
    servicer = TicketServiceImpl()
    store = await get_permission_store()

    # Allow client_a -> server_b
    await store.set_rule("client_a", "server_b", PermissionEffect.ALLOW)

    # 1. Issue ticket for allowed pair
    req = pb2.IssueTicketRequest(
        source_service="client_a",
        target_service="server_b",
        ttl_seconds=120,
    )
    resp = await servicer.IssueTicket(req, mock_context)

    assert resp.ticket != ""
    assert resp.expires_at > int(time.time())
    assert mock_context.code == grpc.StatusCode.OK

    # 2. Issue ticket for unauthorized pair
    mock_context_denied = mock_context.__class__()
    req_denied = pb2.IssueTicketRequest(
        source_service="unauthorized_client",
        target_service="server_b",
        ttl_seconds=120,
    )
    resp_denied = await servicer.IssueTicket(req_denied, mock_context_denied)

    assert resp_denied.ticket == ""
    assert mock_context_denied.code == grpc.StatusCode.PERMISSION_DENIED
    assert "not allowed to call" in mock_context_denied.details


@pytest.mark.asyncio
async def test_validate_ticket_success(test_session, mock_context):
    servicer = TicketServiceImpl()
    store = await get_permission_store()
    await store.set_rule("client_a", "server_b", PermissionEffect.ALLOW)

    # Issue ticket
    issue_resp = await servicer.IssueTicket(
        pb2.IssueTicketRequest(source_service="client_a", target_service="server_b", ttl_seconds=300),
        mock_context,
    )

    # Validate ticket
    val_req = pb2.ValidateTicketRequest(
        ticket=issue_resp.ticket,
        target_service="server_b",
    )
    val_resp = await servicer.ValidateTicket(val_req, mock_context)

    assert val_resp.valid is True
    assert val_resp.source_service == "client_a"
    assert val_resp.target_service == "server_b"


@pytest.mark.asyncio
async def test_validate_ticket_audience_mismatch(test_session, mock_context):
    servicer = TicketServiceImpl()
    store = await get_permission_store()
    await store.set_rule("client_a", "server_b", PermissionEffect.ALLOW)

    # Issue ticket for server_b
    issue_resp = await servicer.IssueTicket(
        pb2.IssueTicketRequest(source_service="client_a", target_service="server_b", ttl_seconds=300),
        mock_context,
    )

    # Validate against server_c
    val_req = pb2.ValidateTicketRequest(
        ticket=issue_resp.ticket,
        target_service="server_c",
    )
    val_resp = await servicer.ValidateTicket(val_req, mock_context)

    assert val_resp.valid is False
    assert mock_context.code == grpc.StatusCode.PERMISSION_DENIED
    assert "Audience mismatch" in mock_context.details


@pytest.mark.asyncio
async def test_validate_ticket_invalid_signature(test_session, mock_context):
    servicer = TicketServiceImpl()

    val_req = pb2.ValidateTicketRequest(
        ticket="invalid.jwt.token",
        target_service="server_b",
    )
    val_resp = await servicer.ValidateTicket(val_req, mock_context)

    assert val_resp.valid is False
    assert mock_context.code == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_validate_ticket_expired(test_session, mock_context):
    servicer = TicketServiceImpl()

    # Generate an expired ticket
    now = int(time.time())
    payload = {
        "jti": "expired-uuid",
        "sub": "client_a",
        "aud": "server_b",
        "iat": now - 300,
        "exp": now - 100,
    }
    expired_token = _encode_jwt(payload)

    val_req = pb2.ValidateTicketRequest(
        ticket=expired_token,
        target_service="server_b",
    )
    val_resp = await servicer.ValidateTicket(val_req, mock_context)

    assert val_resp.valid is False
    assert mock_context.code == grpc.StatusCode.UNAUTHENTICATED
    assert "Ticket expired" in mock_context.details


@pytest.mark.asyncio
async def test_validate_ticket_revoked(test_session, mock_context):
    servicer = TicketServiceImpl()
    store = await get_permission_store()
    await store.set_rule("client_a", "server_b", PermissionEffect.ALLOW)

    # Issue ticket
    issue_resp = await servicer.IssueTicket(
        pb2.IssueTicketRequest(source_service="client_a", target_service="server_b", ttl_seconds=300),
        mock_context,
    )

    payload = _decode_jwt(issue_resp.ticket)
    assert payload is not None
    jti = payload["jti"]

    # Revoke ticket in database
    test_session.add(RevokedTicket(jti=jti, reason="compromised"))
    await test_session.commit()

    # Validate revoked ticket
    val_req = pb2.ValidateTicketRequest(
        ticket=issue_resp.ticket,
        target_service="server_b",
    )
    val_resp = await servicer.ValidateTicket(val_req, mock_context)

    assert val_resp.valid is False
    assert mock_context.code == grpc.StatusCode.UNAUTHENTICATED
    assert "Ticket revoked" in mock_context.details


@pytest.mark.asyncio
async def test_permission_crud_via_api(test_session, mock_context):
    servicer = TicketServiceImpl()

    # 1. SetPermission
    set_req = pb2.SetPermissionRequest(
        source_service="service_x",
        target_service="service_y",
        effect=pb2.PERMISSION_EFFECT_ALLOW,
        description="Allow x to call y",
    )
    set_resp = await servicer.SetPermission(set_req, mock_context)
    assert set_resp.success is True

    # 2. CheckPermission
    check_req = pb2.CheckPermissionRequest(
        source_service="service_x",
        target_service="service_y",
    )
    check_resp = await servicer.CheckPermission(check_req, mock_context)
    assert check_resp.allowed is True
    assert check_resp.effect == pb2.PERMISSION_EFFECT_ALLOW

    # 3. ListPermissions
    list_resp = await servicer.ListPermissions(pb2.ListPermissionsRequest(), mock_context)
    matched = [r for r in list_resp.rules if r.source_service == "service_x" and r.target_service == "service_y"]
    assert len(matched) == 1
    assert matched[0].description == "Allow x to call y"

    # 4. RemovePermission
    remove_req = pb2.RemovePermissionRequest(
        source_service="service_x",
        target_service="service_y",
    )
    remove_resp = await servicer.RemovePermission(remove_req, mock_context)
    assert remove_resp.success is True

    # 5. CheckPermission after removal
    check_resp2 = await servicer.CheckPermission(check_req, mock_context)
    assert check_resp2.allowed is False


@pytest.mark.asyncio
async def test_remove_non_existent_permission_returns_not_found(test_session, mock_context):
    servicer = TicketServiceImpl()
    remove_req = pb2.RemovePermissionRequest(
        source_service="unknown_a",
        target_service="unknown_b",
    )
    remove_resp = await servicer.RemovePermission(remove_req, mock_context)

    assert remove_resp.success is False
    assert mock_context.code == grpc.StatusCode.NOT_FOUND
