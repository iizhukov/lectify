"""Local Docker authority; durable execution ownership stays in the database."""
import asyncio

import grpc
from structlog.contextvars import get_contextvars

from generated.docker_sandbox import DockerSandbox, DockerCommandError
from generated.grpc_server.grpc_app import WorkerServiceBase
from generated.protos.server import index_pb2 as pb
from generated.observability.operations import operation as observe


class WorkerServiceImpl(WorkerServiceBase):
    def __init__(self, sandbox=None):
        self.sandbox = sandbox or DockerSandbox()

    async def _call(self, context, operation):
        # source_service is populated from the validated TAS ticket, not a user header.
        if get_contextvars().get('source_service') != 'orchestrator':
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Orchestrator ticket required')
        try:
            with observe('container',operation.__name__):
                return await operation()
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid container assignment')
        except (DockerCommandError, OSError, TimeoutError):
            await context.abort(grpc.StatusCode.UNAVAILABLE, 'Host container operation failed')

    async def Identity(self, request, context):
        async def identity():
            return pb.WorkerIdentity(daemon_id=await self.sandbox.daemon_identity())
        return await self._call(context, identity)

    async def Create(self, request, context):
        async def create():
            attempt = request.attempt
            # Settle Docker creation even if the gRPC deadline expires. The
            # persisted attempt and deterministic name allow later reconciliation.
            task = asyncio.create_task(self.sandbox.create(execution_id=attempt.execution_id,
                node_id=attempt.node_id, fence=attempt.fence, attempt_id=attempt.attempt_id,
                role=attempt.role, image=request.image, environment=dict(request.environment),
                network=request.network or 'none', network_aliases=list(request.network_aliases)))
            identity, cancelled = await self.sandbox._settle(task)
            if cancelled:
                raise asyncio.CancelledError()
            return pb.ContainerIdentity(container_id=identity)
        return await self._call(context, create)

    async def Start(self, request, context):
        async def start():
            await self.sandbox.verify_managed(request.container_id)
            await self.sandbox.start(request.container_id)
            return pb.Empty()
        return await self._call(context, start)

    async def Remove(self, request, context):
        async def remove():
            await self.sandbox.verify_managed(request.container_id)
            await self.sandbox.remove(request.container_id)
            return pb.Empty()
        return await self._call(context, remove)

    async def Reconcile(self, request, context):
        async def reconcile():
            removed = await self.sandbox.reconcile(execution_id=request.execution_id,
                node_id=request.node_id, fence=request.fence, attempt_id=request.attempt_id,
                role=request.role)
            return pb.ReconcileResult(removed=removed)
        return await self._call(context, reconcile)
