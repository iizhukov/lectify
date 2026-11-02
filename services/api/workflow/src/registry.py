"""Read immutable plugin schemas through the orchestrator's authenticated API."""
import asyncio
import json
import grpc

from generated.grpc_client.grpc_clients import GrpcClients
from generated.protos.clients.orchestrator import index_pb2 as pb, index_pb2_grpc as rpc
from generated.user_auth.client import delegated_metadata
from generated.workflow_validation import RegistryUnavailableError


async def registry_schemas(graph, context, *, clients_factory=None):
    identities = sorted({(node['plugin_id'], node['plugin_version']) for node in graph['nodes']})
    if not 1 <= len(identities) <= 256:
        raise ValueError('Invalid plugin count')
    clients = (clients_factory or GrpcClients)(source_service='api_workflow')
    try:
        stub = rpc.OrchestratorServiceStub(clients.channel('orchestrator'))
        metadata = delegated_metadata(context)
        # Bound concurrent RPCs as well as the total validation deadline.
        semaphore = asyncio.Semaphore(16)
        async def load(identity):
            async with semaphore:
                try:
                    response = await stub.GetPluginManifest(pb.GetPluginManifestRequest(
                        plugin_id=identity[0], version=identity[1]), metadata=metadata, timeout=4)
                except grpc.aio.AioRpcError as error:
                    if error.code() == grpc.StatusCode.NOT_FOUND:
                        raise ValueError('Unknown or inactive plugin version') from None
                    raise RegistryUnavailableError('Plugin registry unavailable') from None
            if len(response.manifest_json.encode()) > 1048576:
                raise RegistryUnavailableError('Plugin schema exceeds limit')
            plugin = json.loads(response.manifest_json)['plugin']
            if (plugin['name'], plugin['version']) != identity:
                raise RegistryUnavailableError('Plugin registry identity mismatch')
            return identity[0] + '@' + identity[1], plugin
        async with asyncio.timeout(5):
            tasks = [asyncio.create_task(load(identity)) for identity in identities]
            try:
                return dict(await asyncio.gather(*tasks))
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await clients.close_all()
