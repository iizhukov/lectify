"""Durable launch intent. Commit preparation before invoking Docker transport."""
import re
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import select, update, or_

from src.engine.dispatch import guard_execution_write,database_epoch
from src.models import ContainerAttemptModel, WorkflowNodeExecutionModel, WorkflowExecutionModel, WorkflowDispatchModel


async def prepare_worker_launch(session, workers, *, execution_id, node_id, owner, fence, role, image, now=None):
    """Choose and persist placement under the same execution lease lock."""
    if not await guard_execution_write(session, execution_id, (owner,fence), now):
        raise RuntimeError('Worker placement lease is not active')
    existing = await session.scalar(select(ContainerAttemptModel).where(
        ContainerAttemptModel.execution_id == execution_id,
        ContainerAttemptModel.node_id == node_id,
        ContainerAttemptModel.fence == fence, ContainerAttemptModel.role == role))
    daemon_id, sandbox = workers.choose(execution_id,node_id,role,
        daemon_id=existing.daemon_id if existing is not None else None)
    attempt_id = await prepare_launch(session, execution_id=execution_id,node_id=node_id,
        owner=owner,fence=fence,role=role,image=image,daemon_id=daemon_id,now=now)
    if attempt_id is None:
        raise RuntimeError('Worker placement node is not active')
    return attempt_id, daemon_id, sandbox


@asynccontextmanager
async def launch_on_worker(factory, workers, *, execution_id, node_id, owner, fence, role, image,
                           environment, network='none', network_aliases=()):
    async with factory() as session:
        _, daemon_id, sandbox = await prepare_worker_launch(session,workers,
            execution_id=execution_id,node_id=node_id,owner=owner,fence=fence,role=role,image=image)
        await session.commit()
    if await sandbox.daemon_identity() != daemon_id:
        raise RuntimeError('Docker worker context does not match assigned daemon')
    async with launch_container(factory,sandbox,execution_id=execution_id,node_id=node_id,
            owner=owner,fence=fence,role=role,image=image,environment=environment,
            network=network,network_aliases=network_aliases) as identity:
        yield identity


async def prepare_launch(session, *, execution_id, node_id, owner, fence, role, image, daemon_id, now=None):
    if not isinstance(daemon_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', daemon_id):
        raise ValueError('Invalid Docker daemon identity')
    if role not in ('plugin', 'agent'):
        raise ValueError('Invalid container role')
    if not isinstance(image, str) or len(image) > 512 or not re.fullmatch(
            r'(?:[A-Za-z0-9][A-Za-z0-9./:_-]*@)?sha256:[a-f0-9]{64}', image):
        raise ValueError('An immutable container image is required')
    if type(fence) is not int or fence <= 0:
        raise ValueError('Invalid launch fence')
    if not await guard_execution_write(session, execution_id, (owner, fence), now):
        return None
    node = await session.scalar(select(WorkflowNodeExecutionModel).where(
        WorkflowNodeExecutionModel.execution_id == execution_id,
        WorkflowNodeExecutionModel.node_id == node_id))
    if node is None or node.state not in ('PENDING', 'PROVISIONING', 'BUFFERING', 'PROCESSING'):
        return None
    existing = await session.scalar(select(ContainerAttemptModel).where(
        ContainerAttemptModel.execution_id == execution_id,
        ContainerAttemptModel.node_id == node_id,
        ContainerAttemptModel.fence == fence, ContainerAttemptModel.role == role))
    if existing is not None:
        if existing.image != image or existing.daemon_id != daemon_id:
            raise ValueError('Launch assignment image is immutable')
        return existing.id
    attempt = ContainerAttemptModel(id=uuid.uuid4().hex, execution_id=execution_id,
        node_id=node_id, fence=fence, role=role, image=image, daemon_id=daemon_id)
    session.add(attempt)
    await session.flush()
    return attempt.id


async def begin_launch(session, *, attempt_id, execution_id, owner, fence, now=None):
    """Claim the one external create attempt. Commit True before calling Docker.

    CREATING is deliberately not retried as PREPARED after an uncertain failure:
    the daemon may already have created a container. Reconciliation owns that
    state, preventing a second create from racing an unresolved first request.
    """
    if not await guard_execution_write(session, execution_id, (owner, fence), now):
        return False
    result = await session.execute(update(ContainerAttemptModel).where(
        ContainerAttemptModel.id == attempt_id,
        ContainerAttemptModel.execution_id == execution_id,
        ContainerAttemptModel.fence == fence,
        ContainerAttemptModel.state == 'PREPARED',
    ).values(state='CREATING').returning(ContainerAttemptModel.id))
    return result.scalar_one_or_none() is not None


async def record_container(session, *, attempt_id, execution_id, owner, fence, container_id, now=None):
    """Persist a verified daemon identity while the launch lease is still owned."""
    if not isinstance(container_id, str) or not re.fullmatch(r'[a-f0-9]{64}', container_id):
        raise ValueError('Invalid container identity')
    if not await guard_execution_write(session, execution_id, (owner, fence), now):
        return False
    result = await session.execute(update(ContainerAttemptModel).where(
        ContainerAttemptModel.id == attempt_id,
        ContainerAttemptModel.execution_id == execution_id,
        ContainerAttemptModel.fence == fence,
        ContainerAttemptModel.state == 'CREATING',
        ContainerAttemptModel.container_id.is_(None),
    ).values(state='CREATED', container_id=container_id).returning(ContainerAttemptModel.id))
    return result.scalar_one_or_none() is not None


@asynccontextmanager
async def launch_container(factory, sandbox, *, execution_id, node_id, owner, fence,
                           role, image, environment, network='none', network_aliases=()):
    """Commit durable intent before Docker; persist its identity before start."""
    scope = dict(execution_id=execution_id, owner=owner, fence=fence)
    daemon_id = await sandbox.daemon_identity()
    async with factory() as session:
        attempt_id = await prepare_launch(session, **scope, node_id=node_id, role=role, image=image, daemon_id=daemon_id)
        if attempt_id is None:
            raise RuntimeError('Container launch lease is not active')
        await session.commit()
    async with factory() as session:
        if not await begin_launch(session, **scope, attempt_id=attempt_id):
            raise RuntimeError('Container launch is already claimed or lease was lost')
        await session.commit()
    container_id = None
    cleaned = False
    try:
        async with sandbox.allocated(execution_id=execution_id, node_id=node_id, fence=fence,
                attempt_id=attempt_id, role=role, image=image, environment=environment,
                network=network, network_aliases=network_aliases) as identity:
            container_id = identity
            async with factory() as session:
                if not await record_container(session, **scope, attempt_id=attempt_id, container_id=identity):
                    raise RuntimeError('Container launch lease was lost before start')
                await session.commit()

            # Serialize start against cancellation and ownership replacement.
            # Docker start is bounded by the generated transport deadline.
            async with factory() as session:
                if not await guard_execution_write(session, execution_id, (owner, fence)):
                    raise RuntimeError('Container launch lease was lost before start')
                await sandbox.start(identity)
                await session.commit()
            yield identity
        cleaned = True
    finally:
        # When body raises, allocated still removes the container before
        # propagating. Keep unresolved attempts discoverable on any exception;
        # reconciliation can verify whether removal actually completed.
        if container_id is not None and cleaned:
            async with factory() as session:
                await session.execute(update(ContainerAttemptModel).where(
                    ContainerAttemptModel.id == attempt_id,
                    ContainerAttemptModel.container_id == container_id,
                ).values(state='CLEANED'))
                await session.commit()



async def cleanup_created_containers(factory, sandbox, *, limit=100,execution_id=None):
    """Reconcile confirmed containers after terminal state or fence replacement.

    Missing CREATING attempts remain observable: a delayed Create may still
    produce a container. Repeated probes remove it once it appears; they never
    declare an uncertain outcome clean just because Docker currently has no ID.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid cleanup batch limit')
    daemon_id = await sandbox.daemon_identity()
    async with factory() as session:
        rows = list((await session.scalars(select(ContainerAttemptModel).join(
            WorkflowExecutionModel, WorkflowExecutionModel.id == ContainerAttemptModel.execution_id,
        ).join(WorkflowDispatchModel, WorkflowDispatchModel.execution_id == ContainerAttemptModel.execution_id).where(
            ContainerAttemptModel.state.in_(('PREPARED','CREATING','CREATED')),
            ContainerAttemptModel.daemon_id == daemon_id,
            *([ContainerAttemptModel.execution_id==execution_id] if execution_id is not None else []),
            or_(WorkflowExecutionModel.state.in_(('COMPLETED','FAILED','CANCELLED')),
                WorkflowDispatchModel.fence > ContainerAttemptModel.fence),
        ).order_by(ContainerAttemptModel.cleanup_checked_at,ContainerAttemptModel.created_at, ContainerAttemptModel.id).limit(limit))).all())
    cleaned = 0
    for row in rows:
        try:
            removed = row.state=='PREPARED' or await sandbox.reconcile(execution_id=row.execution_id, node_id=row.node_id,
                fence=row.fence, role=row.role, attempt_id=row.id)
        except (RuntimeError, TimeoutError, OSError):
            # Preserve the durable job on daemon/ownership failures. The next
            # scheduler run retries; no error is mistaken for container absence.
            continue
        async with factory() as session:
            result = await session.execute(update(ContainerAttemptModel).where(
                ContainerAttemptModel.id == row.id, ContainerAttemptModel.state == row.state,
                ContainerAttemptModel.container_id == row.container_id,
            ).values(state='CLEANED' if removed or row.state!='CREATING' else 'CREATING',
                cleanup_checked_at=database_epoch(session)))
            await session.commit()
            if removed or row.state!='CREATING': cleaned += result.rowcount
    return cleaned
