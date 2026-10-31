"""Compose trusted runtime assignments with generated gRPC transport."""
from contextlib import aclosing, AsyncExitStack
import asyncio

from generated.plugin_runtime_client import PluginRuntimeClient
from generated.plugin_control_client import PluginControlClient
from generated.protos.plugins import index_pb2 as pb
from generated.stream_router import StreamChunkData


class RuntimeStreamDispatcher:
    supports_streaming = True
    requires_credentials = True

    def __init__(self, assignments):
        # An async context-manager factory owned by trusted deployment policy.
        # Workflow parameters cannot supply endpoints, tokens or image commands.
        self.assignments = assignments
        self._clients = {}
        self._tasks = {}

    async def stream_node(self, *, execution_id, node, inputs, ownership, initial_inputs):
        key = (execution_id, node['id'])
        if key in self._tasks:
            raise RuntimeError('Node runtime is already active')
        task = asyncio.current_task()
        self._tasks[key] = task
        try:
            async with self.assignments(execution_id=execution_id, node=node,
                    ownership=ownership, initial_inputs=initial_inputs) as assignment:
                async with AsyncExitStack() as lifecycle:
                    if 'control' in assignment:
                        control = assignment['control']
                        agent = await lifecycle.enter_async_context(PluginControlClient(
                            control['endpoint'], execution_id, node['id'], control['token'],
                            tls=control.get('tls'), timeout=control.get('timeout',15)))
                        await lifecycle.enter_async_context(agent.running(control['command_id']))
                    async with PluginRuntimeClient(assignment['endpoint'], execution_id, node['id'],
                            assignment['token'], tls=assignment.get('tls'),
                            timeout=assignment.get('timeout', 300)) as client:
                        self._clients[key] = client
                        async def frames():
                            async for frame in inputs:
                                yield pb.DataChunk(stream_name=frame.stream_name, sequence_number=frame.sequence,
                                    payload=frame.payload, is_last=frame.is_last, metadata=frame.metadata)
                        async with aclosing(client.process(frames(), assignment['outputs'])) as outputs:
                            async for frame in outputs:
                                yield StreamChunkData(stream_name=frame.stream_name, sequence=frame.sequence_number,
                                    payload=frame.payload, is_last=frame.is_last, metadata=dict(frame.metadata))
        finally:
            if self._tasks.get(key) is task:
                self._clients.pop(key, None)
                self._tasks.pop(key, None)

    async def stop_node(self, execution_id, node_id):
        task = self._tasks.get((execution_id, node_id))
        if task is not None and task is not asyncio.current_task():
            if not task.done() and not task.cancelling():
                task.cancel()
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
