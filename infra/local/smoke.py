"""Exercise real backend, PostgreSQL, S3 and Docker plugins through generated gRPC clients."""
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0,'/app/services/tools/client')
from generated.grpc_client.grpc_clients import GrpcClients
from generated.protos.clients.api_auth import index_pb2 as auth_pb, index_pb2_grpc as auth_rpc
from generated.protos.clients.api_workflow import index_pb2 as wf_pb, index_pb2_grpc as wf_rpc
from generated.protos.clients.api_execution import index_pb2 as ex_pb, index_pb2_grpc as ex_rpc
from generated.protos.clients.orchestrator import index_pb2 as orch_pb, index_pb2_grpc as orch_rpc
from generated.protos.clients.api_file import index_pb2 as file_pb, index_pb2_grpc as file_rpc


async def main():
    clients = GrpcClients(source_service='tools_client')
    try:
        auth = auth_rpc.AuthServiceStub(clients.channel('api_auth'))
        credentials = json.loads(Path('/run/config/secrets.json').read_text())
        login = await auth.Login(auth_pb.LoginRequest(username='admin',password=credentials['admin']),timeout=15,wait_for_ready=True)
        metadata = (('x-user-authorization','Bearer '+login.access_token),)
        executions = ex_rpc.ExecutionServiceStub(clients.channel('api_execution'))
        files = file_rpc.FileServiceStub(clients.channel('api_file'))
        # A repeated smoke after deployment restart also verifies old artifacts.
        previous = await executions.ListExecutions(ex_pb.ListExecutionsRequest(page_size=100),metadata=metadata,timeout=15)
        for record in previous.executions:
            if record.state != 'EXECUTION_STATE_COMPLETED': continue
            saved = await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=record.execution_id),metadata=metadata,timeout=15)
            identifiers = [node.output_artifacts['result'] for node in saved.nodes if 'result' in node.output_artifacts]
            if identifiers:
                persisted = [frame async for frame in files.Download(file_pb.FileRequest(id=identifiers[0]),metadata=metadata,timeout=15)]
                assert persisted[-1].is_last
                break
        registry = orch_rpc.OrchestratorServiceStub(clients.channel('orchestrator'))
        for plugin in ('io/text_input','io/file_input','format/text_to_md','io/text_output','io/file_output'):
            import yaml
            manifest = yaml.safe_load((Path('/app/plugins')/plugin/'plugin.yaml').read_text())
            await registry.RegisterPluginManifest(orch_pb.RegisterPluginManifestRequest(
                plugin_id=manifest['plugin']['name'],version=manifest['plugin']['version'],
                manifest_yaml=json.dumps(manifest)),metadata=metadata,timeout=20,wait_for_ready=True)
        workflows = wf_rpc.WorkflowServiceStub(clients.channel('api_workflow'))
        graph = wf_pb.WorkflowGraph(nodes=[
            wf_pb.GraphNode(id='input',plugin_id='text_input',plugin_version='0.1.0',parameters_json='{}',
                input_mapping=[wf_pb.InputMapping(target_field='value',source='input.text',transform='passthrough')]),
            wf_pb.GraphNode(id='format',plugin_id='text_to_md',plugin_version='0.1.0',parameters_json='{"title":"ETL result"}'),
            wf_pb.GraphNode(id='output',plugin_id='text_output',plugin_version='0.1.0',parameters_json='{}')],edges=[
            wf_pb.GraphEdge(from_node_id='input',from_output='text',to_node_id='format',to_input='text_stream'),
            wf_pb.GraphEdge(from_node_id='format',from_output='md_stream',to_node_id='output',to_input='text')])
        workflow = await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name='Local ETL',graph=graph),metadata=metadata,timeout=20)
        updated = await workflows.UpdateWorkflow(wf_pb.UpdateWorkflowRequest(id=workflow.id,expected_version=workflow.version,
            name='Local ETL edited',graph=graph),metadata=metadata,timeout=20)
        request = ex_pb.StartWorkflowRequest(workflow_id=updated.id,expected_version=updated.version,
            request_key=uuid.uuid4().hex,initial_inputs={'text':'Hello ETL'})
        started = await executions.StartWorkflow(request,metadata=metadata,timeout=30)
        repeated = await executions.StartWorkflow(request,metadata=metadata,timeout=30)
        assert repeated.execution_id == started.execution_id
        async with asyncio.timeout(120):
            while True:
                status = await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=started.execution_id),metadata=metadata,timeout=15)
                if status.state in ('EXECUTION_STATE_COMPLETED','EXECUTION_STATE_FAILED','EXECUTION_STATE_CANCELLED'): break
                await asyncio.sleep(.5)
        assert status.state == 'EXECUTION_STATE_COMPLETED', status.error_message
        output = next(node for node in status.nodes if node.node_id == 'output')
        assert 'result' in output.output_artifacts, 'Completed output node has no persisted artifact'
        file_id = output.output_artifacts['result']
        frames = [frame async for frame in files.Download(file_pb.FileRequest(id=file_id),metadata=metadata,timeout=15)]
        content = b''.join(frame.chunk for frame in frames if frame.WhichOneof('data') == 'chunk')
        assert content == b'# ETL result\n\nHello ETL\n', content
        assert frames[-1].is_last
        assert output.bytes_streamed_in == len(content)
        import hashlib
        binary = b'\x00\xffETL binary\n'
        async def upload():
            yield file_pb.UploadFrame(sequence=0,metadata=file_pb.UploadMetadata(filename='source.bin',
                content_type='application/octet-stream',size_bytes=len(binary),sha256=hashlib.sha256(binary).hexdigest()))
            yield file_pb.UploadFrame(sequence=1,chunk=binary,is_last=True)
        source = await files.Upload(upload(),metadata=metadata,timeout=15)
        file_graph = wf_pb.WorkflowGraph(nodes=[
            wf_pb.GraphNode(id='input',plugin_id='file_input',plugin_version='0.1.0',parameters_json='{}',
                input_mapping=[wf_pb.InputMapping(target_field='file_id',source='input.file',transform='passthrough')]),
            wf_pb.GraphNode(id='output',plugin_id='file_output',plugin_version='0.1.0',parameters_json='{}')],edges=[
            wf_pb.GraphEdge(from_node_id='input',from_output='data',to_node_id='output',to_input='data')])
        file_workflow = await workflows.CreateWorkflow(wf_pb.CreateWorkflowRequest(name='Binary ETL',graph=file_graph),
            metadata=metadata,timeout=20)
        copied = await executions.StartWorkflow(ex_pb.StartWorkflowRequest(workflow_id=file_workflow.id,
            expected_version=file_workflow.version,request_key=uuid.uuid4().hex,initial_inputs={'file':source.id}),
            metadata=metadata,timeout=30)
        async with asyncio.timeout(120):
            while True:
                file_status = await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=copied.execution_id),
                    metadata=metadata,timeout=15)
                if file_status.state in ('EXECUTION_STATE_COMPLETED','EXECUTION_STATE_FAILED'): break
                await asyncio.sleep(.5)
        assert file_status.state == 'EXECUTION_STATE_COMPLETED', file_status.error_message
        artifact = next(node for node in file_status.nodes if node.node_id=='output').output_artifacts['result']
        copied_frames = [frame async for frame in files.Download(file_pb.FileRequest(id=artifact),metadata=metadata,timeout=15)]
        assert b''.join(frame.chunk for frame in copied_frames if frame.WhichOneof('data')=='chunk') == binary
        import grpc
        async def rejected(awaitable, code):
            try: await awaitable
            except grpc.aio.AioRpcError as error: assert error.code() == code,error.code()
            else: raise AssertionError('Expected rejected request')
        invalid = ex_pb.StartWorkflowRequest(workflow_id=updated.id,expected_version=updated.version,request_key=uuid.uuid4().hex)
        await rejected(executions.StartWorkflow(invalid,metadata=metadata,timeout=20),grpc.StatusCode.INVALID_ARGUMENT)
        stranger = await auth.Register(auth_pb.RegisterRequest(username='u'+uuid.uuid4().hex,
            email=uuid.uuid4().hex+'@local.invalid',password=uuid.uuid4().hex,full_name='Other user'),timeout=15)
        stranger_metadata = (('x-user-authorization','Bearer '+stranger.access_token),)
        await rejected(executions.GetStatus(ex_pb.ExecutionRequest(execution_id=started.execution_id),
            metadata=stranger_metadata,timeout=15),grpc.StatusCode.NOT_FOUND)
        await rejected(files.GetFile(file_pb.FileRequest(id=file_id),metadata=stranger_metadata,timeout=15),grpc.StatusCode.NOT_FOUND)
        request.request_key = uuid.uuid4().hex
        cancel_run = await executions.StartWorkflow(request,metadata=metadata,timeout=20)
        cancelled = await executions.Cancel(ex_pb.CancelRequest(execution_id=cancel_run.execution_id,reason='Smoke cancellation'),
            metadata=metadata,timeout=30)
        assert cancelled.state == 'EXECUTION_STATE_CANCELLED'
        assert (await executions.GetStatus(ex_pb.ExecutionRequest(execution_id=cancel_run.execution_id),
            metadata=metadata,timeout=15)).state == 'EXECUTION_STATE_CANCELLED'
        history = await executions.ListExecutions(ex_pb.ListExecutionsRequest(page_size=100),metadata=metadata,timeout=15)
        assert started.execution_id in {row.execution_id for row in history.executions}
        import urllib.request
        import urllib.parse
        async with asyncio.timeout(60):
            while True:
                query = urllib.parse.urlencode({'query':'sum(application_operation_completed_total{operation="plugin",outcome="completed"})'})
                def read_metrics():
                    with urllib.request.urlopen('http://prometheus:9090/api/v1/query?'+query,timeout=5) as response:
                        return json.load(response)
                result = await asyncio.to_thread(read_metrics)
                values = result.get('data',{}).get('result',[])
                if values and float(values[0]['value'][1]) >= 3: break
                await asyncio.sleep(2)
        print('PASS: login → register plugins → create/edit DAG → idempotent execution → Docker plugins → S3 download')
        print('PASS: execution history, persisted byte counts, OTLP → Collector → Prometheus plugin metrics')
        print('PASS: upload binary file → scoped file input → file output → byte-exact S3 download')
        print('PASS: cancellation, missing-input rejection, private execution/file access and persisted prior artifacts')
        print('Execution:',started.execution_id)
    finally:
        await clients.close_all()

if __name__ == '__main__': asyncio.run(main())
