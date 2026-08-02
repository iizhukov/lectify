import os
import time
import uuid
import json

import grpc

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

import generated.protos.server.index_pb2 as pb2
from generated.grpc_server.grpc_app import TicketServiceBase
from generated.logger import get_logger
from generated.db.connection import get_session_factory
from src.models import RevokedTicket

from src.policy.models import PermissionEffect
from src.policy.store import get_permission_store


log = get_logger("service")


def _load_or_generate_key() -> tuple[rsa.RSAPrivateKey, bytes]:
    key_pem = os.environ.get("INFRA_TAS_JWT_PRIVATE_KEY")
    if key_pem:
        private_key = serialization.load_pem_private_key(
            key_pem.encode(),
            password=None,
            backend=default_backend(),
        )
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return private_key, public_pem

    log.warning("jwt_key_not_set", message="INFRA_TAS_JWT_PRIVATE_KEY not set — generating ephemeral key")
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem


_private_key, _public_key_pem = _load_or_generate_key()


def get_public_key_pem() -> str:
    return _public_key_pem.decode()


def _encode_jwt(payload: dict) -> str:
    """Simple JWT encoding with RS256 (no external deps for TAS itself)."""
    header = {"alg": "RS256", "typ": "JWT"}
    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    message = f"{header_b64}.{payload_b64}".encode()
    signature = _private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = _b64encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _decode_jwt(token: str) -> dict | None:
    """Decode and verify JWT with RS256. Returns payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts

        message = f"{header_b64}.{payload_b64}".encode()
        signature = _b64decode(sig_b64)

        try:
            _private_key.public_key().verify(
                signature, message, padding.PKCS1v15(), hashes.SHA256()
            )
        except Exception:
            return None

        payload = json.loads(_b64decode(payload_b64))
        return payload
    except Exception:
        return None


def _b64encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(data: str) -> bytes:
    import base64
    padding_len = 4 - len(data) % 4
    if padding_len != 4:
        data += "=" * padding_len
    return base64.urlsafe_b64decode(data)


class TicketServiceImpl(TicketServiceBase):
    async def IssueTicket(self, request, context):
        store = await get_permission_store()
        allowed = await store.check_permission(
            request.source_service, request.target_service
        )
        if not allowed:
            log.warning("ticket_issue_denied",
                        source=request.source_service,
                        target=request.target_service,
                        reason="permission_denied")
            context.set_code(grpc.StatusCode.PERMISSION_DENIED)
            context.set_details(
                f"Service '{request.source_service}' is not allowed to "
                f"call service '{request.target_service}'"
            )
            return pb2.IssueTicketResponse()

        now = int(time.time())
        ttl = request.ttl_seconds or 60
        if ttl > 3600:
            ttl = 3600

        payload = {
            "jti": str(uuid.uuid4()),
            "sub": request.source_service,
            "aud": request.target_service,
            "iat": now,
            "exp": now + ttl,
        }

        ticket = _encode_jwt(payload)
        log.info("ticket_issued",
                 source=request.source_service,
                 target=request.target_service,
                 ttl=ttl)

        return pb2.IssueTicketResponse(
            ticket=ticket,
            expires_at=payload["exp"],
        )

    async def ValidateTicket(self, request, context):
        payload = _decode_jwt(request.ticket)
        if payload is None:
            log.warning("ticket_validation_failed", reason="invalid_signature")
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Invalid ticket signature")
            return pb2.ValidateTicketResponse(valid=False)

        if payload.get("aud") != request.target_service:
            log.warning("ticket_validation_failed", reason="audience_mismatch",
                        expected=request.target_service, got=payload.get("aud"))
            context.set_code(grpc.StatusCode.PERMISSION_DENIED)
            context.set_details("Audience mismatch")
            return pb2.ValidateTicketResponse(valid=False)

        now = int(time.time())
        if payload.get("exp", 0) < now:
            log.warning("ticket_validation_failed", reason="expired")
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Ticket expired")
            return pb2.ValidateTicketResponse(valid=False)

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(RevokedTicket).where(RevokedTicket.jti == payload.get("jti"))
            )
            if result.scalar_one_or_none() is not None:
                log.warning("ticket_validation_failed", reason="revoked")
                context.set_code(grpc.StatusCode.UNAUTHENTICATED)
                context.set_details("Ticket revoked")
                return pb2.ValidateTicketResponse(valid=False)

        log.info("ticket_validated",
                 source=payload.get("sub"),
                 target=payload.get("aud"))
        return pb2.ValidateTicketResponse(
            valid=True,
            source_service=payload.get("sub", ""),
            target_service=payload.get("aud", ""),
        )

    async def GetPublicKey(self, request, context):
        log.info("public_key_requested")
        return pb2.GetPublicKeyResponse(
            public_key=get_public_key_pem(),
            algorithm="RS256",
        )

    async def SetPermission(self, request, context):
        store = await get_permission_store()
        effect = PermissionEffect.from_proto(request.effect)
        if effect == PermissionEffect.DENY and request.effect == 0:
            effect = PermissionEffect.ALLOW

        await store.set_rule(
            source=request.source_service,
            target=request.target_service,
            effect=effect,
            description=request.description or "",
        )
        log.info("permission_set_via_api",
                 source=request.source_service,
                 target=request.target_service,
                 effect=effect.value)
        return pb2.SetPermissionResponse(success=True)

    async def RemovePermission(self, request, context):
        store = await get_permission_store()
        removed = await store.remove_rule(
            source=request.source_service,
            target=request.target_service,
        )
        if not removed:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(
                f"No permission rule found for "
                f"'{request.source_service}' -> '{request.target_service}'"
            )
            return pb2.RemovePermissionResponse(success=False)
        return pb2.RemovePermissionResponse(success=True)

    async def ListPermissions(self, request, context):
        store = await get_permission_store()
        rules = store.list_rules()
        pb_rules = []
        for rule in rules:
            pb_rules.append(pb2.PermissionRule(
                source_service=rule.source_service,
                target_service=rule.target_service,
                effect=rule.effect.to_proto(),
                description=rule.description,
            ))
        log.info("permission_list_requested", count=len(rules))
        return pb2.ListPermissionsResponse(rules=pb_rules)

    async def CheckPermission(self, request, context):
        store = await get_permission_store()
        allowed, effect = await store.check_permission_full(
            request.source_service,
            request.target_service,
        )
        effect_proto = effect.to_proto() if effect else 0
        return pb2.CheckPermissionResponse(
            allowed=allowed,
            effect=effect_proto,
        )
