"""Generated, temporary workflow service exercised with real SQLite and gRPC."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
SERVICE = Path(__file__).resolve().parents[1]
GENERATE = r'''
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from config.models import ServiceManifest
from context import ServiceContext
from generators.services import base
from generators.services.settings import SettingsGenerator
from generators.services.logger import LoggerGenerator
from generators.services.db import DbGenerator
from generators.services.grpc_server import GrpcServerGenerator
from generators.services.grpc_client import GrpcClientGenerator
from generators.services.user_auth import UserAuthGenerator
from generators.services.workflow_validation import WorkflowValidationGenerator
from generators.services.ticket_auth import TicketAuthGenerator
import yaml
manifest = ServiceManifest.model_validate(yaml.safe_load(Path('service.yaml').read_text()))
base.get_settings = lambda: SimpleNamespace(POSTGRES_PORT=5432)
base.get_context_manager = lambda: SimpleNamespace(get_service_context=lambda name: ServiceContext())
for generator in (SettingsGenerator, LoggerGenerator, DbGenerator, GrpcServerGenerator,
                  GrpcClientGenerator, TicketAuthGenerator, UserAuthGenerator, WorkflowValidationGenerator):
    generator(manifest, Path('generated').resolve()).generate()
'''
PREFIX = r'''
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import grpc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from generated.db.base import BaseModel
from generated.protos.server import index_pb2 as pb
from src.service import WorkflowServiceImpl
from src.models import WorkflowSnapshot

class Error(Exception):
    def __init__(self, code, details): self.code, self.details = code, details

class Context:
    def __init__(self, user=None, admin=False):
        if user is not None: self.lectify_principal = SimpleNamespace(user_id=user, is_admin=admin)
    async def abort(self, code, details): raise Error(code, details)
    def invocation_metadata(self): return [('x-user-id', 'alice'), ('x-admin', 'true')]

alice, bob, admin = Context('alice'), Context('bob'), Context('admin', True)

async def reject(awaitable, code):
    try: await awaitable
    except Error as error:
        assert error.code == code, (error.code, error.details)
        return
    raise AssertionError('Expected failure')

SCHEMAS = {'text@1.0.0': {'name':'text','version':'1.0.0','active':True,
    'inputs':[{'name':'in','type':'stream/text'}], 'outputs':[{'name':'out','type':'stream/text'}],
    'parameters':[{'name':'temperature','type':'float','default':0.5}]}}

def graph():
    return pb.WorkflowGraph(nodes=[pb.GraphNode(id='a',plugin_id='text',plugin_version='1.0.0'),
        pb.GraphNode(id='b',plugin_id='text',plugin_version='1.0.0')],
        edges=[pb.GraphEdge(from_node_id='a',from_output='out',to_node_id='b',to_input='in')])

def update(row, **options):
    values = dict(id=row.id,expected_version=row.version,name=row.name,description=row.description,
                  graph=row.graph,is_public=row.is_public)
    values.update(options)
    return pb.UpdateWorkflowRequest(**values)

async def database(filename):
    engine = create_async_engine('sqlite+aiosqlite:///' + filename)
    async with engine.begin() as connection: await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine,expire_on_commit=False)
'''

BUSINESS = PREFIX + r'''
async def main():
    engine,factory = await database('workflow.sqlite')
    service = WorkflowServiceImpl(session_factory=factory,registry_provider=lambda graph: SCHEMAS)
    second = WorkflowServiceImpl(session_factory=factory,registry_provider=lambda graph: SCHEMAS)
    request = pb.CreateWorkflowRequest(name='Lecture',description='private',graph=graph())
    await reject(service.CreateWorkflow(request,Context()),grpc.StatusCode.UNAUTHENTICATED)
    await reject(WorkflowServiceImpl(session_factory=factory).CreateWorkflow(request,alice),grpc.StatusCode.UNAVAILABLE)
    row = await service.CreateWorkflow(request,alice)
    assert row.owner_id == 'alice' and row.version == 1
    assert json.loads(row.graph.nodes[0].parameters_json) == {'temperature':0.5}
    await reject(service.GetWorkflow(pb.IdRequest(id=row.id),bob),grpc.StatusCode.NOT_FOUND)
    await reject(service.GetWorkflow(pb.IdRequest(id=row.id),admin),grpc.StatusCode.NOT_FOUND)
    assert not (await service.ListWorkflows(pb.ListRequest(),bob)).workflows
    await reject(service.CreateWorkflow(pb.CreateWorkflowRequest(name='global',graph=graph(),global_workflow=True),alice),grpc.StatusCode.PERMISSION_DENIED)
    global_row = await service.CreateWorkflow(pb.CreateWorkflowRequest(name='global',graph=graph(),global_workflow=True),admin)
    assert global_row.owner_id == '' and global_row.is_public
    await reject(service.UpdateWorkflow(update(global_row,name='stolen'),alice),grpc.StatusCode.PERMISSION_DENIED)
    global_row = await service.UpdateWorkflow(update(global_row,name='global edited'),admin)
    assert global_row.version == 2
    snap = await service.CreateSnapshot(pb.CreateSnapshotRequest(workflow_id=row.id,expected_version=1,request_key='execution-1'),alice)
    assert snap.created_by == 'alice' and snap.workflow_version == 1 and len(snap.content_hash) == 64
    assert await second.CreateSnapshot(pb.CreateSnapshotRequest(workflow_id=row.id,expected_version=1,request_key='execution-1'),alice) == snap
    await reject(service.GetSnapshot(pb.IdRequest(id=snap.id),bob),grpc.StatusCode.NOT_FOUND)
    await reject(service.CreateSnapshot(pb.CreateSnapshotRequest(workflow_id=global_row.id,expected_version=2,request_key='execution-1'),alice),grpc.StatusCode.ALREADY_EXISTS)
    results = await asyncio.gather(service.UpdateWorkflow(update(row,name='first edit'),alice),
        second.UpdateWorkflow(update(row,name='second edit'),alice),return_exceptions=True)
    assert sum(isinstance(item,pb.Workflow) for item in results) == 1
    assert sum(isinstance(item,Error) and item.code==grpc.StatusCode.ABORTED for item in results) == 1
    changed = next(item for item in results if isinstance(item,pb.Workflow))
    assert changed.version == 2
    original = await service.GetSnapshot(pb.IdRequest(id=snap.id),alice)
    assert original.name == 'Lecture' and original.graph == snap.graph
    await reject(service.DeleteWorkflow(pb.DeleteRequest(id=row.id,expected_version=1),alice),grpc.StatusCode.ABORTED)
    public = await service.UpdateWorkflow(update(changed,is_public=True),alice)
    assert (await second.GetWorkflow(pb.IdRequest(id=row.id),bob)).id == row.id
    await reject(second.UpdateWorkflow(update(public,name='stolen'),bob),grpc.StatusCode.PERMISSION_DENIED)
    forked = await second.ForkWorkflow(pb.ForkWorkflowRequest(id=row.id,expected_version=public.version),bob)
    assert forked.owner_id == 'bob' and not forked.is_public and forked.graph == public.graph
    await service.DeleteWorkflow(pb.DeleteRequest(id=row.id,expected_version=public.version),alice)
    assert await service.GetSnapshot(pb.IdRequest(id=snap.id),alice) == snap
    assert await service.CreateSnapshot(pb.CreateSnapshotRequest(workflow_id=row.id,expected_version=1,request_key='execution-1'),alice) == snap
    node_req = pb.CreateNodeTemplateRequest(plugin_id='text',plugin_version='1.0.0',name='Summarizer')
    node = await service.CreateNodeTemplate(node_req,alice)
    assert node.owner_id == 'alice' and json.loads(node.parameters_json)=={'temperature':0.5}
    await reject(service.GetNodeTemplate(pb.IdRequest(id=node.id),bob),grpc.StatusCode.NOT_FOUND)
    await reject(service.CreateNodeTemplate(pb.CreateNodeTemplateRequest(plugin_id='text',plugin_version='1.0.0',name='global',global_node=True),alice),grpc.StatusCode.PERMISSION_DENIED)
    global_node = await service.CreateNodeTemplate(pb.CreateNodeTemplateRequest(plugin_id='text',plugin_version='1.0.0',name='global',global_node=True),admin)
    assert (await service.GetNodeTemplate(pb.IdRequest(id=global_node.id),bob)).owner_id == ''
    node = await service.UpdateNodeTemplate(pb.UpdateNodeTemplateRequest(id=node.id,expected_version=1,
        plugin_id='text',plugin_version='1.0.0',name='edited',parameters_json='{"temperature":0.7}'),alice)
    assert node.version == 2
    await reject(service.DeleteNodeTemplate(pb.DeleteRequest(id=node.id,expected_version=1),alice),grpc.StatusCode.ABORTED)
    await service.DeleteNodeTemplate(pb.DeleteRequest(id=node.id,expected_version=2),alice)
    assert len((await service.ListNodeTemplates(pb.ListRequest(),alice)).nodes)==1
    assert len((await service.ListNodeTemplates(pb.ListRequest(own_only=True),alice)).nodes)==0
    await service.DeleteNodeTemplate(pb.DeleteRequest(id=global_node.id,expected_version=global_node.version),admin)
    for malformed in ['{"temperature":true}','{"temperature":NaN}','{"temperature":1,"temperature":2}','[]']:
        bad = graph();bad.nodes[0].parameters_json=malformed
        await reject(service.CreateWorkflow(pb.CreateWorkflowRequest(name='bad',graph=bad),alice),grpc.StatusCode.INVALID_ARGUMENT)
    for case in ['duplicate','cycle','unknownplugin','port']:
        bad = graph()
        if case=='duplicate':bad.nodes[1].id='a'
        elif case=='cycle':bad.edges.append(pb.GraphEdge(from_node_id='b',from_output='out',to_node_id='a',to_input='in'))
        elif case=='unknownplugin':bad.nodes[0].plugin_id='unknown'
        elif case=='port':bad.edges[0].from_output='absent'
        await reject(service.CreateWorkflow(pb.CreateWorkflowRequest(name='bad',graph=bad),alice),grpc.StatusCode.INVALID_ARGUMENT)
    await reject(service.ListWorkflows(pb.ListRequest(page_size=101),alice),grpc.StatusCode.INVALID_ARGUMENT)
    await engine.dispose()

asyncio.run(main())
'''


@pytest.fixture
def generated_service(tmp_path):
    project = tmp_path / 'project'
    service = project / 'services/api/workflow'
    service.mkdir(parents=True)
    shutil.copytree(SERVICE / 'src',service/'src')
    shutil.copytree(SERVICE / 'migrations',service/'migrations')
    shutil.copy(SERVICE/'service.yaml',service/'service.yaml')
    for name in ('workflow','auth'):
        protocol = project/'proto/api'/name
        protocol.mkdir(parents=True)
        shutil.copy(ROOT/f'proto/api/{name}/index.proto',protocol/'index.proto')
    for category, name in (('orchestrator', 'orchestrator'), ('infra', 'tas')):
        dependency = project / 'services' / category / name
        dependency.mkdir(parents=True)
        shutil.copy(ROOT / 'services' / category / name / 'service.yaml', dependency / 'service.yaml')
        protocol = project / 'proto' / category / name
        protocol.mkdir(parents=True)
        shutil.copy(ROOT / 'proto' / category / name / 'index.proto', protocol / 'index.proto')
    auth = project/'services/api/auth'
    auth.mkdir(parents=True)
    shutil.copy(ROOT/'services/api/auth/service.yaml',auth/'service.yaml')
    environment = dict(os.environ,CODEGEN_ROOT=str(project),PYTHONPATH=str(service))
    result = subprocess.run([sys.executable,'-c',GENERATE,str(ROOT/'utils/codegen/src')],
        cwd=service,env=environment,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return service,environment


def run(generated_service, scenario):
    service,environment = generated_service
    result = subprocess.run([sys.executable,'-c',scenario],cwd=service,env=environment,
                            text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_persisted_crud_acl_versions_snapshots_and_graph_validation(generated_service):
    run(generated_service,BUSINESS)


def test_default_registry_adapter_reads_pinned_schemas_over_grpc(generated_service):
    run(generated_service, PREFIX + r'''
from src import registry
from generated.protos.clients.orchestrator import index_pb2 as registry_pb, index_pb2_grpc as registry_rpc
calls = []
class Registry(registry_rpc.OrchestratorServiceServicer):
    async def GetPluginManifest(self, request, context):
        assert dict(context.invocation_metadata())['x-user-authorization'] == 'Bearer verified'
        calls.append((request.plugin_id, request.version))
        if request.plugin_id != 'text':
            await context.abort(grpc.StatusCode.NOT_FOUND, 'missing')
        return registry_pb.GetPluginManifestResponse(manifest_json=json.dumps({'plugin':SCHEMAS['text@1.0.0']}))
class VerifiedContext(Context):
    def invocation_metadata(self): return [('x-user-authorization','Bearer verified')]
async def main():
    server = grpc.aio.server()
    registry_rpc.add_OrchestratorServiceServicer_to_server(Registry(),server)
    port = server.add_insecure_port('127.0.0.1:0')
    await server.start()
    class Clients:
        def __init__(self, **kwargs):
            assert kwargs == {'source_service':'api_workflow'}
            self.connection = grpc.aio.insecure_channel('127.0.0.1:'+str(port))
        def channel(self, name):
            assert name == 'orchestrator'
            return self.connection
        async def close_all(self): await self.connection.close()
    registry.GrpcClients = Clients
    try:
        service = WorkflowServiceImpl()
        normalized = await service._graph(graph(),VerifiedContext('alice'))
        assert len(normalized['nodes']) == 2 and calls == [('text','1.0.0')]
        invalid = graph()
        invalid.nodes[0].plugin_id = 'unknown'
        await reject(service._graph(invalid,VerifiedContext('alice')),grpc.StatusCode.INVALID_ARGUMENT)
    finally:
        await server.stop(0)
asyncio.run(main())
''')

RPC = PREFIX + r'''
from generated.protos.server import index_pb2_grpc as rpc
from generated.user_auth.interceptor import UserAuthServerInterceptor

class Verifier:
    async def authenticate(self, token):
        user = {'alice-token':'alice','bob-token':'bob','admin-token':'admin'}.get(token,'')
        return SimpleNamespace(valid=bool(user),user_id=user,is_admin=user=='admin',username=user)

async def rpc_error(awaitable, expected):
    try: await awaitable
    except grpc.aio.AioRpcError as error:
        assert error.code()==expected,error
        return
    raise AssertionError('Expected RPC rejection')

async def main():
    engine,factory = await database('workflow-rpc.sqlite')
    server = grpc.aio.server(interceptors=[UserAuthServerInterceptor(client=Verifier())])
    rpc.add_WorkflowServiceServicer_to_server(WorkflowServiceImpl(session_factory=factory,
        registry_provider=lambda graph: SCHEMAS),server)
    port = server.add_insecure_port('127.0.0.1:0')
    assert port
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f'127.0.0.1:{port}') as channel:
            client = rpc.WorkflowServiceStub(channel)
            request = pb.CreateWorkflowRequest(name='Private',graph=graph())
            await rpc_error(client.CreateWorkflow(request,metadata=[('x-user-id','alice'),('x-admin','true')],timeout=3),grpc.StatusCode.UNAUTHENTICATED)
            alice_headers = [('x-user-authorization','Bearer alice-token')]
            bob_spoof = [('x-user-authorization','Bearer bob-token'),('x-user-id','alice'),('x-admin','true')]
            row = await client.CreateWorkflow(request,metadata=alice_headers,timeout=3)
            assert row.owner_id=='alice'
            await rpc_error(client.GetWorkflow(pb.IdRequest(id=row.id),metadata=bob_spoof,timeout=3),grpc.StatusCode.NOT_FOUND)
            bob_row = await client.CreateWorkflow(request,metadata=bob_spoof,timeout=3)
            assert bob_row.owner_id=='bob'
            await rpc_error(client.CreateWorkflow(pb.CreateWorkflowRequest(name='Global',graph=graph(),global_workflow=True),
                metadata=bob_spoof,timeout=3),grpc.StatusCode.PERMISSION_DENIED)
            snapshot = await client.CreateSnapshot(pb.CreateSnapshotRequest(workflow_id=row.id,expected_version=1,
                request_key='rpc-execution'),metadata=alice_headers,timeout=3)
            assert snapshot.created_by=='alice'
            await client.DeleteWorkflow(pb.DeleteRequest(id=row.id,expected_version=1),metadata=alice_headers,timeout=3)
            assert await client.GetSnapshot(pb.IdRequest(id=snapshot.id),metadata=alice_headers,timeout=3)==snapshot
    finally:
        await server.stop(0)
        await engine.dispose()

asyncio.run(main())
'''


def test_real_grpc_generated_identity_rejects_owner_and_admin_spoofing(generated_service):
    run(generated_service,RPC)


RACE = PREFIX + r'''
async def main():
    engine,factory = await database('workflow-race.sqlite')
    normal = WorkflowServiceImpl(session_factory=factory,registry_provider=lambda graph: SCHEMAS)
    row = await normal.CreateWorkflow(pb.CreateWorkflowRequest(name='Published',graph=graph(),is_public=True),alice)
    selected,resume = asyncio.Event(),asyncio.Event()
    async def paused_registry(graph):
        selected.set()
        await resume.wait()
        return SCHEMAS
    paused = WorkflowServiceImpl(session_factory=factory,registry_provider=paused_registry)
    copying = asyncio.create_task(paused.CreateSnapshot(pb.CreateSnapshotRequest(workflow_id=row.id,
        expected_version=1,request_key='racing-copy'),bob))
    await asyncio.wait_for(selected.wait(),2)
    row = await normal.UpdateWorkflow(update(row,is_public=False),alice)
    resume.set()
    await reject(copying,grpc.StatusCode.ABORTED)
    async with factory() as session:
        assert (await session.execute(select(WorkflowSnapshot))).first() is None
    # A stable source can be snapshotted concurrently with one idempotency key.
    request = pb.CreateSnapshotRequest(workflow_id=row.id,expected_version=row.version,request_key='same-request')
    first,second = await asyncio.gather(normal.CreateSnapshot(request,alice),normal.CreateSnapshot(request,alice))
    assert first.id==second.id
    async with factory() as session:
        assert len((await session.execute(select(WorkflowSnapshot))).scalars().all())==1
    await engine.dispose()

asyncio.run(main())
'''


def test_snapshot_visibility_race_and_concurrent_idempotency(generated_service):
    run(generated_service,RACE)


MIGRATIONS = r'''
import importlib.util
from pathlib import Path
from sqlalchemy import create_engine,inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
from generated.db.base import BaseModel
from src import models
engine = create_engine('sqlite:///workflow-migration.sqlite')
modules=[]
for path in sorted(Path('migrations/versions').glob('*.py')):
    spec=importlib.util.spec_from_file_location(path.stem,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    modules.append(module)
with engine.begin() as connection:
    with Operations.context(MigrationContext.configure(connection)):
        for module in modules: module.upgrade()
        for name,table in BaseModel.metadata.tables.items():
            assert {item['name'] for item in inspect(connection).get_columns(name)}==set(table.columns.keys())
        unique=inspect(connection).get_unique_constraints('workflow_snapshots')
        assert any(set(item['column_names'])=={'created_by','request_key'} for item in unique)
        for module in reversed(modules):module.downgrade()
        assert not any(name.startswith('workflow_') for name in inspect(connection).get_table_names())
        for module in modules:module.upgrade()
engine.dispose()
'''


def test_workflow_migrations_roundtrip_and_model_parity(generated_service):
    run(generated_service,MIGRATIONS)
