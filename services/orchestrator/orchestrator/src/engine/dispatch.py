"""Database lease rules. Callers commit claims before starting external work."""
import hashlib
import secrets

from sqlalchemy import BigInteger, cast, func, select, update

from src.models import WorkflowDispatchModel as Dispatch, WorkflowExecutionModel as Execution


def _validate(owner, now, ttl):
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
        raise ValueError('A nonempty worker owner is required')
    if isinstance(now, bool) or not isinstance(now, int) or now < 0:
        raise ValueError('Lease time must be a nonnegative integer')
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 3600:
        raise ValueError('Lease TTL must be between 1 and 3600 seconds')


def _running(execution_id):
    return select(Execution.id).where(Execution.id == execution_id, Execution.state == 'RUNNING').exists()


def _now(session, value):
    if value is not None:
        return value
    clock = func.clock_timestamp() if session.get_bind().dialect.name == 'postgresql' else func.current_timestamp()
    return cast(func.extract('epoch', clock), BigInteger)


async def claim(session, execution_id, owner, now=None, ttl=30):
    _validate(owner, 0 if now is None else now, ttl)
    now = _now(session, now)
    result = await session.execute(update(Dispatch).where(
        Dispatch.execution_id == execution_id,
        Dispatch.state.in_(('PENDING', 'LEASED')),
        Dispatch.lease_expires_at <= now,
        _running(execution_id),
    ).values(owner=owner, state='LEASED', lease_expires_at=now + ttl,
             fence=Dispatch.fence + 1, report_token_hash=None, report_token_fence=None).returning(Dispatch.fence))
    return result.scalar_one_or_none()


async def renew(session, execution_id, owner, fence, now=None, ttl=30):
    _validate(owner, 0 if now is None else now, ttl)
    now = _now(session, now)
    result = await session.execute(update(Dispatch).where(
        Dispatch.execution_id == execution_id, Dispatch.state == 'LEASED',
        Dispatch.owner == owner, Dispatch.fence == fence, Dispatch.lease_expires_at > now,
        _running(execution_id),
    ).values(lease_expires_at=now + ttl).returning(Dispatch.fence))
    return result.scalar_one_or_none() is not None


async def guard_execution_write(session, execution_id, ownership, now=None):
    """Lock lease then execution until commit; reject late or cancelled writes."""
    now = _now(session, now)
    if ownership is not None:
        owner, fence = ownership
        locked = await session.execute(update(Dispatch).where(
            Dispatch.execution_id == execution_id, Dispatch.state == 'LEASED',
            Dispatch.owner == owner, Dispatch.fence == fence, Dispatch.lease_expires_at > now,
        ).values(fence=Dispatch.fence).returning(Dispatch.fence))
        if locked.scalar_one_or_none() is None:
            return False
    locked = await session.execute(update(Execution).where(
        Execution.id == execution_id, Execution.state == 'RUNNING',
    ).values(id=Execution.id).returning(Execution.id))
    return locked.scalar_one_or_none() is not None


async def pending_executions(session, limit=100):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Dispatch batch size must be between 1 and 100')
    result = await session.execute(select(Execution).join(
        Dispatch, Dispatch.execution_id == Execution.id,
    ).where(
        Execution.state == 'RUNNING', Dispatch.state.in_(('PENDING', 'LEASED')),
        Dispatch.lease_expires_at <= _now(session, None),
    ).order_by(Execution.created_at, Execution.id).limit(limit))
    return list(result.scalars())


async def issue_report_capability(session, execution_id, owner, fence, now=None):
    """Rotate reporting authority under the lease lock; commit before delivery.

    Only a hash is persisted. The returned bearer token belongs to this claim,
    and a new claim clears it before any replacement worker starts work.
    """
    _validate(owner, 0 if now is None else now, 30)
    if type(fence) is not int or fence <= 0:
        raise ValueError('A positive lease fence is required')
    if not await guard_execution_write(session, execution_id, (owner, fence), now):
        return None
    token = secrets.token_urlsafe(32)
    await session.execute(update(Dispatch).where(
        Dispatch.execution_id == execution_id,
    ).values(report_token_hash=hashlib.sha256(token.encode('ascii')).hexdigest(),
             report_token_fence=fence))
    return token
