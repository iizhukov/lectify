"""Host agent policy and lifecycle; Docker is replaced with a recorded transport."""
import subprocess
import sys
from pathlib import Path


def test_host_agent_lifecycle_and_access():
    script = r'''
import asyncio
import grpc
from structlog.contextvars import bind_contextvars, clear_contextvars
from generated.protos.server import index_pb2 as pb
from src.service import WorkerServiceImpl

class Denied(Exception): pass
class Context:
    async def abort(self, code, message):
        assert code == grpc.StatusCode.PERMISSION_DENIED
        raise Denied()
class Sandbox:
    def __init__(self): self.calls = []
    async def daemon_identity(self): return 'host-a'
    async def create(self, **spec): self.calls.append(('create', spec)); return 'a'*64
    async def verify_managed(self, identity): self.calls.append(('verify', identity))
    async def start(self, identity): self.calls.append(('start', identity))
    async def remove(self, identity): self.calls.append(('remove', identity))
    async def reconcile(self, **spec): self.calls.append(('reconcile', spec)); return True
    @staticmethod
    async def _settle(task): return await task, False

async def main():
    sandbox = Sandbox()
    service, context = WorkerServiceImpl(sandbox), Context()
    clear_contextvars()
    try: await service.Identity(pb.Empty(), context)
    except Denied: pass
    else: raise AssertionError('Unauthenticated access accepted')
    bind_contextvars(source_service='api_workflow')
    try: await service.Remove(pb.ContainerIdentity(container_id='a'*64), context)
    except Denied: pass
    else: raise AssertionError('Non-orchestrator service accepted')
    assert sandbox.calls == []
    bind_contextvars(source_service='orchestrator')
    assert (await service.Identity(pb.Empty(), context)).daemon_id == 'host-a'
    request = pb.ContainerAssignment(attempt=pb.AttemptIdentity(execution_id='run', node_id='node',
        fence=1, attempt_id='b'*32, role='plugin'), image='sha256:'+'c'*64,
        environment={'KEY':'value'}, network='pipeline', network_aliases=['node'])
    identity = await service.Create(request, context)
    assert identity.container_id == 'a'*64
    assert sandbox.calls[0][1]['attempt_id'] == 'b'*32
    await service.Start(identity, context)
    await service.Remove(identity, context)
    assert [call[0] for call in sandbox.calls] == ['create','verify','start','verify','remove']
    assert (await service.Reconcile(request.attempt, context)).removed
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
