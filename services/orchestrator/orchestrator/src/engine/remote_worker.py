"""Sandbox transport over authenticated host-agent gRPC, without Docker access."""
from generated.docker_sandbox import DockerSandbox, DockerCommandError
from generated.grpc_client.grpc_clients import GrpcClients
from generated.protos.clients.orchestrator_worker import index_pb2 as pb, index_pb2_grpc as rpc
import grpc


class RemoteWorker(DockerSandbox):
    def __init__(self, endpoint, *, clients_factory=GrpcClients):
        self.endpoint = endpoint
        self.clients_factory = clients_factory

    async def _rpc(self, method, request):
        clients = self.clients_factory(source_service='orchestrator')
        try:
            stub = rpc.WorkerServiceStub(clients.channel('orchestrator_worker', self.endpoint))
            return await getattr(stub, method)(request, timeout=45)
        except grpc.aio.AioRpcError:
            raise DockerCommandError('Host agent request failed') from None
        finally:
            await clients.close_all()

    async def daemon_identity(self):
        return (await self._rpc('Identity', pb.Empty())).daemon_id

    async def create(self, *, execution_id, node_id, fence, attempt_id, image, environment,
                     network='none', role='plugin', network_aliases=()):
        response = await self._rpc('Create', pb.ContainerAssignment(
            attempt=pb.AttemptIdentity(execution_id=execution_id, node_id=node_id,
                fence=fence, attempt_id=attempt_id, role=role), image=image,
            environment=environment, network=network, network_aliases=network_aliases))
        self._validate_id(response.container_id)
        return response.container_id

    async def start(self, container_id):
        self._validate_id(container_id)
        await self._rpc('Start', pb.ContainerIdentity(container_id=container_id))

    async def remove(self, container_id):
        self._validate_id(container_id)
        await self._rpc('Remove', pb.ContainerIdentity(container_id=container_id))

    async def reconcile(self, **attempt):
        return (await self._rpc('Reconcile', pb.AttemptIdentity(**attempt))).removed
