"""Real gRPC host-agent/Docker lifecycle, with an explicit test-only ticket gate.

The production service uses generated TAS interceptors. This probe supplies a
fixed verified service identity in a loopback server; it does not test TAS.
"""
import asyncio
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


async def serve(port_file):
    sys.path.insert(0, str(ROOT / 'services/orchestrator/worker'))
    import grpc
    from structlog.contextvars import bind_contextvars
    from generated.protos.server import index_pb2_grpc as rpc
    from src.service import WorkerServiceImpl

    class TestWorker(WorkerServiceImpl):
        async def _call(self, context, operation):
            bind_contextvars(source_service='orchestrator')
            return await super()._call(context, operation)
    server = grpc.aio.server()
    rpc.add_WorkerServiceServicer_to_server(TestWorker(), server)
    port = server.add_insecure_port('127.0.0.1:0')
    await server.start()
    Path(port_file).write_text(str(port))
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    try:
        await stop.wait()
    finally:
        await server.stop(0)


async def verify():
    sys.path.insert(0, str(ROOT / 'services/orchestrator/orchestrator'))
    import grpc
    from src.engine.remote_worker import RemoteWorker
    from generated.docker_sandbox import DockerCommandError
    import uuid
    class Clients:
        def __init__(self, **kwargs): self.channel_instance = None
        def channel(self, name, endpoint):
            self.channel_instance = grpc.aio.insecure_channel(endpoint)
            return self.channel_instance
        async def close_all(self):
            if self.channel_instance: await self.channel_instance.close()

    # Use only an existing local image. Never pull or call a paid provider.
    image = subprocess.run(['docker','image','inspect','python:3.12-slim','--format','{{.Id}}'],
        capture_output=True,text=True,check=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='lectify-host-worker-') as directory:
        port_file = Path(directory) / 'port'
        process = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).resolve()),
            'serve', str(port_file))
        try:
            async with asyncio.timeout(15):
                while not port_file.exists():
                    if process.returncode is not None: raise RuntimeError('Test worker exited')
                    await asyncio.sleep(.05)
            worker = RemoteWorker('127.0.0.1:' + port_file.read_text(), clients_factory=Clients)
            daemon = await worker.daemon_identity()
            assert daemon
            scope = dict(execution_id=uuid.uuid4().hex,node_id='node',fence=1,
                attempt_id=uuid.uuid4().hex,role='plugin')
            async with worker.allocated(**scope,image=image,environment={}) as identity:
                await worker.start(identity)
                inspected = subprocess.run(['docker','inspect','--format',
                    '{{index .Config.Labels "lectify.attempt"}}',identity],capture_output=True,text=True,check=True)
                assert inspected.stdout.strip() == scope['attempt_id']
            assert not await worker.reconcile(**scope)
            try:
                await worker.create(**dict(scope,attempt_id=uuid.uuid4().hex),
                    image='mutable:tag',environment={})
            except DockerCommandError: pass
            else: raise AssertionError('Mutable image accepted')
            print('Host agent: real gRPC create/start/remove, placement identity and image validation passed.')
        finally:
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)


if __name__ == '__main__':
    asyncio.run(serve(sys.argv[2]) if len(sys.argv) > 1 and sys.argv[1] == 'serve' else verify())
