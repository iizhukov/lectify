"""Durable, encrypted reset delivery with database leases shared across replicas.

No remote call occurs while accepting a reset request. The encryption key must
come from a secret store, never from this database. External mail delivery is
at-least-once; retries deliver the same single-use reset credential.
"""
import asyncio
import hashlib
import math
import secrets
import time
import uuid

from cryptography.fernet import Fernet
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from src.models import PasswordReset, ResetDelivery, User

RESET_TTL = 3600
MAX_ATTEMPTS = 8


class ResetOutbox:
    def __init__(self, factory_provider, key, delivery, *, clock=time.time):
        try:
            self._cipher = Fernet(key)
        except (TypeError, ValueError):
            raise ValueError('Reset delivery requires a valid separate Fernet key') from None
        self._factory_provider = factory_provider
        self._delivery = delivery
        self._clock = clock

    def now(self):
        return int(self._clock())

    async def enqueue(self, email):
        # Perform the same crypto work for every address. Plaintext never enters
        # persistent state; a leaked DB alone cannot reconstruct reset tokens.
        token = 'pr_' + secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        ciphertext = self._cipher.encrypt(token.encode())
        now = self.now()
        async with self._factory_provider()() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if user is not None:
                # Acquire the account write lock only if its security version is
                # still the one read above. Password changes use the same row:
                # enqueue either precedes their cleanup or declines a stale read.
                guarded = (await session.execute(update(User).where(
                    User.id == user.id, User.security_version == user.security_version,
                ).values(security_version=User.security_version).returning(User.id))).scalar_one_or_none()
                if guarded is None:
                    await session.rollback()
                    return
                obsolete = ((PasswordReset.expires_at <= now)
                            | (PasswordReset.security_version != user.security_version))
                expired = select(PasswordReset.token_hash).where(
                    PasswordReset.user_id == user.id, obsolete)
                await session.execute(delete(ResetDelivery).where(ResetDelivery.reset_hash.in_(expired)))
                await session.execute(delete(PasswordReset).where(
                    PasswordReset.user_id == user.id, obsolete))
                pending = (await session.execute(select(PasswordReset.token_hash).where(
                    PasswordReset.user_id == user.id))).scalars().first()
                if pending is None:
                    session.add(PasswordReset(token_hash=digest, user_id=user.id,
                                              expires_at=now + RESET_TTL, security_version=user.security_version))
                    await session.flush()
                    session.add(ResetDelivery(id=str(uuid.uuid4()), user_id=user.id, reset_hash=digest,
                                              token_ciphertext=ciphertext, due_at=now,
                                              lease_until=0, lease_owner='', attempts=0))
            try:
                await session.commit()
            except IntegrityError:
                # Concurrent anonymous requests may race for the unique per-user
                # reset. The winner's transaction owns its outbox row.
                await session.rollback()

    async def deliver(self, *, limit=100, timeout=20.0, lease_seconds=30):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError('Delivery batch limit must be between 1 and 1000')
        if not math.isfinite(timeout) or not 0 < timeout <= 60 or lease_seconds < timeout + 5:
            raise ValueError('Delivery lease must exceed the bounded callback timeout by at least five seconds')
        now = self.now()
        async with self._factory_provider()() as session:
            candidates = (await session.execute(select(ResetDelivery.id).join(
                PasswordReset, PasswordReset.token_hash == ResetDelivery.reset_hash).join(
                User, User.id == PasswordReset.user_id).where(
                    ResetDelivery.delivered_at.is_(None), ResetDelivery.due_at <= now,
                    ResetDelivery.lease_until <= now, ResetDelivery.attempts < MAX_ATTEMPTS,
                    PasswordReset.expires_at > now, PasswordReset.security_version == User.security_version,
                ).order_by(ResetDelivery.due_at, ResetDelivery.id).limit(limit))).scalars().all()
        result = {'delivered': 0, 'failed': 0}
        for delivery_id in candidates:
            owner = str(uuid.uuid4())
            now = self.now()
            async with self._factory_provider()() as session:
                claimed = (await session.execute(update(ResetDelivery).where(
                    ResetDelivery.id == delivery_id, ResetDelivery.delivered_at.is_(None),
                    ResetDelivery.due_at <= now, ResetDelivery.lease_until <= now,
                    ResetDelivery.attempts < MAX_ATTEMPTS,
                ).values(lease_owner=owner, lease_until=now + lease_seconds,
                         attempts=ResetDelivery.attempts + 1).returning(ResetDelivery.id))).scalar_one_or_none()
                await session.commit()
                if claimed is None:
                    continue
                row = (await session.execute(select(ResetDelivery.token_ciphertext, ResetDelivery.reset_hash, User.email).join(
                    PasswordReset, PasswordReset.token_hash == ResetDelivery.reset_hash).join(
                    User, User.id == PasswordReset.user_id).where(
                        ResetDelivery.id == delivery_id, ResetDelivery.lease_owner == owner,
                        PasswordReset.expires_at > now, PasswordReset.security_version == User.security_version,
                    ))).first()
            if row is None:
                continue
            succeeded = False
            try:
                token = self._cipher.decrypt(row.token_ciphertext).decode('ascii')
                if hashlib.sha256(token.encode()).hexdigest() != row.reset_hash:
                    raise ValueError('Reset delivery credential binding is invalid')
                await asyncio.wait_for(self._delivery(row.email, token), timeout=timeout)
                succeeded = True
            except Exception:
                # No provider error text: it can contain recipient, token or URL.
                result['failed'] += 1
            async with self._factory_provider()() as session:
                values = {'lease_owner': '', 'lease_until': 0, 'due_at': self.now() + 60}
                if succeeded:
                    values.update(delivered_at=self.now(), token_ciphertext=b'')
                updated = (await session.execute(update(ResetDelivery).where(
                    ResetDelivery.id == delivery_id, ResetDelivery.lease_owner == owner,
                    ResetDelivery.lease_until > self.now(),
                ).values(**values).returning(ResetDelivery.id))).scalar_one_or_none()
                await session.commit()
                if succeeded and updated is not None:
                    result['delivered'] += 1
        return result
