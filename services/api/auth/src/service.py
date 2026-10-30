"""Account and session business rules. Tokens are never stored or logged in plaintext."""
import asyncio
import hashlib
import re
import secrets
import time
import uuid

import grpc
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from generated.db.connection import get_session_factory
from generated.grpc_server.grpc_app import AuthServiceBase
from generated.protos.server import index_pb2 as pb
from src.models import PasswordReset, ResetDelivery, Session, User
from src.reset_delivery import ResetOutbox
from src.passwords import hash_password, validate_password, verify_password

ACCESS_TTL = 900
REFRESH_TTL = 7 * 24 * 3600
RESET_TTL = 3600
# Equal-cost password verification for absent usernames; no fixed valid password.
_DUMMY_HASH = 'pbkdf2_sha256$600000$' + '00' * 16 + '$' + '00' * 32


def token_hash(token):
    if not isinstance(token, str) or not token or len(token) > 512:
        return None
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def principal(user):
    return pb.Principal(user_id=user.id, username=user.username, is_admin=user.is_admin)


class AuthServiceImpl(AuthServiceBase):
    def __init__(self, *, session_factory=None, reset_delivery=None, reset_delivery_key=None, clock=time.time):
        self._factory = session_factory
        self._reset_delivery = reset_delivery
        self._reset_outbox = (ResetOutbox(self.factory, reset_delivery_key, reset_delivery, clock=clock)
                              if reset_delivery_key is not None and reset_delivery is not None else None)
        self._clock = clock

    def factory(self):
        return self._factory or get_session_factory()

    def now(self):
        return int(self._clock())

    async def _password(self, value, context):
        try:
            validate_password(value)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return await asyncio.to_thread(hash_password, value)

    async def _new_session(self, session, user):
        access, refresh = 'la_' + secrets.token_urlsafe(32), 'lr_' + secrets.token_urlsafe(32)
        now = self.now()
        row = Session(id=str(uuid.uuid4()), user_id=user.id,
                      access_hash=token_hash(access), refresh_hash=token_hash(refresh),
                      access_expires_at=now + ACCESS_TTL, refresh_expires_at=now + REFRESH_TTL,
                      security_version=user.security_version)
        session.add(row)
        return pb.AuthResponse(principal=principal(user), access_token=access, refresh_token=refresh,
                               access_expires_at=row.access_expires_at, refresh_expires_at=row.refresh_expires_at)

    async def _access_user(self, session, token, context):
        digest = token_hash(token)
        user = None
        if digest:
            user = (await session.execute(
                select(User).join(Session, Session.user_id == User.id).where(
                    Session.access_hash == digest, Session.access_expires_at > self.now(),
                    Session.security_version == User.security_version,
                )
            )).scalar_one_or_none()
        if user is None:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid or expired credentials')
        return user

    async def Register(self, request, context):
        username, email = request.username.strip().casefold(), request.email.strip().casefold()
        if not re.fullmatch(r'[a-z0-9_][a-z0-9_.-]{2,63}', username):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Username must contain 3–64 ASCII letters, digits, _, . or -')
        if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'A valid email address is required')
        if len(request.full_name) > 256:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Full name is too long')
        encoded = await self._password(request.password, context)
        user = User(id=str(uuid.uuid4()), username=username, email=email, full_name=request.full_name,
                    password_hash=encoded, is_admin=False, security_version=0)
        async with self.factory()() as session:
            try:
                session.add(user)
                await session.flush()
                response = await self._new_session(session, user)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await context.abort(grpc.StatusCode.ALREADY_EXISTS, 'Account identifier is already registered')
        return response

    async def Login(self, request, context):
        username = request.username.strip().casefold()
        async with self.factory()() as session:
            user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
            encoded = user.password_hash if user else _DUMMY_HASH
            valid = await asyncio.to_thread(verify_password, request.password, encoded)
            if user is None or not valid:
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid or expired credentials')
            # The session records the version verified above. A concurrent password
            # reset increments the user version, making this session unusable.
            response = await self._new_session(session, user)
            await session.commit()
        return response

    async def Authenticate(self, request, context):
        async with self.factory()() as session:
            user = await self._access_user(session, request.access_token, context)
            return pb.AuthenticateResponse(user_id=user.id, username=user.username,
                                           is_admin=user.is_admin, valid=True)

    async def Refresh(self, request, context):
        digest = token_hash(request.token)
        async with self.factory()() as session:
            row = (await session.execute(
                select(Session, User).join(User, User.id == Session.user_id).where(
                    Session.refresh_hash == digest, Session.refresh_expires_at > self.now(),
                    Session.security_version == User.security_version,
                )
            )).first() if digest else None
            if row is None:
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid or expired credentials')
            old, user = row
            # DELETE RETURNING is the single-use claim, shared by every replica.
            claimed = (await session.execute(delete(Session).where(
                Session.id == old.id, Session.refresh_hash == digest,
                Session.refresh_expires_at > self.now(),
            ).returning(Session.id))).scalar_one_or_none()
            if claimed is None:
                await session.rollback()
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid or expired credentials')
            response = await self._new_session(session, user)
            await session.commit()
        return response

    async def Logout(self, request, context):
        digest = token_hash(request.token)
        if not digest:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid or expired credentials')
        async with self.factory()() as session:
            await session.execute(delete(Session).where(or_(Session.access_hash == digest, Session.refresh_hash == digest)))
            await session.commit()
        # Idempotent logout does not reveal whether a token was previously valid.
        return pb.OperationResponse(accepted=True)

    async def ChangePassword(self, request, context):
        async with self.factory()() as session:
            user = await self._access_user(session, request.access_token, context)
            if not await asyncio.to_thread(verify_password, request.current_password, user.password_hash):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid or expired credentials')
            new_hash = await self._password(request.new_password, context)
            changed = (await session.execute(update(User).where(
                User.id == user.id, User.password_hash == user.password_hash,
                User.security_version == user.security_version,
            ).values(password_hash=new_hash, security_version=User.security_version + 1)
              .returning(User.id))).scalar_one_or_none()
            if changed is None:
                await session.rollback()
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Credentials changed; authenticate again')
            await session.execute(delete(Session).where(Session.user_id == user.id))
            await session.execute(delete(ResetDelivery).where(ResetDelivery.reset_hash.in_(
                select(PasswordReset.token_hash).where(PasswordReset.user_id == user.id))))
            await session.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
            await session.commit()
        return pb.OperationResponse(accepted=True)

    async def RequestPasswordReset(self, request, context):
        if self._reset_outbox is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE, 'Password reset delivery is not configured')
        email = request.email.strip().casefold()
        if len(email) > 254:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Email address is too long')
        # Enqueue only. Provider latency/failure is never on this public path.
        await self._reset_outbox.enqueue(email)
        return pb.OperationResponse(accepted=True)

    async def deliver_password_resets(self, **options):
        if self._reset_outbox is None:
            raise RuntimeError('Password reset delivery is not configured')
        return await self._reset_outbox.deliver(**options)

    async def ResetPassword(self, request, context):
        digest = token_hash(request.token)
        new_hash = await self._password(request.new_password, context)
        async with self.factory()() as session:
            # Claim the hash atomically; delivery ciphertext is removed in this
            # transaction, including databases without FK cascade enforcement.
            await session.execute(delete(ResetDelivery).where(ResetDelivery.reset_hash == digest))
            reset = (await session.execute(delete(PasswordReset).where(
                PasswordReset.token_hash == digest, PasswordReset.expires_at > self.now(),
            ).returning(PasswordReset.user_id, PasswordReset.security_version))).first() if digest else None
            if reset is None:
                await session.rollback()
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid or expired credentials')
            changed = (await session.execute(update(User).where(
                User.id == reset.user_id, User.security_version == reset.security_version,
            ).values(password_hash=new_hash, security_version=User.security_version + 1)
              .returning(User.id))).scalar_one_or_none()
            if changed is None:
                await session.rollback()
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid or expired credentials')
            await session.execute(delete(Session).where(Session.user_id == reset.user_id))
            await session.execute(delete(ResetDelivery).where(ResetDelivery.reset_hash.in_(
                select(PasswordReset.token_hash).where(PasswordReset.user_id == reset.user_id))))
            await session.execute(delete(PasswordReset).where(PasswordReset.user_id == reset.user_id))
            await session.commit()
        return pb.OperationResponse(accepted=True)
