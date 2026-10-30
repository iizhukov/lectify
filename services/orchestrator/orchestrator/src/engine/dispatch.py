"""Database lease rules. Callers commit claims before starting external work."""
from sqlalchemy import select, update

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


async def claim(session, execution_id, owner, now, ttl=30):
    _validate(owner, now, ttl)
    result = await session.execute(update(Dispatch).where(
        Dispatch.execution_id == execution_id,
        Dispatch.state.in_(('PENDING', 'LEASED')),
        Dispatch.lease_expires_at <= now,
        _running(execution_id),
    ).values(owner=owner, state='LEASED', lease_expires_at=now + ttl,
             fence=Dispatch.fence + 1).returning(Dispatch.fence))
    return result.scalar_one_or_none()


async def renew(session, execution_id, owner, fence, now, ttl=30):
    _validate(owner, now, ttl)
    result = await session.execute(update(Dispatch).where(
        Dispatch.execution_id == execution_id, Dispatch.state == 'LEASED',
        Dispatch.owner == owner, Dispatch.fence == fence, Dispatch.lease_expires_at > now,
        _running(execution_id),
    ).values(lease_expires_at=now + ttl).returning(Dispatch.fence))
    return result.scalar_one_or_none() is not None
