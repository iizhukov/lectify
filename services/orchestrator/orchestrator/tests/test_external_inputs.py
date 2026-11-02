import pytest
from generated.stream_pipeline import run_streaming_graph
from generated.stream_router import StreamChunkData
from generated.stream_dag import DAGValidationError


@pytest.mark.asyncio
async def test_external_input_is_routed_then_fanned_out_with_named_ports():
    nodes = [{'id':'source', 'input_mapping':[{'target_field':'value', 'source':'input.text'}]},
             {'id':'left'}, {'id':'right'}]
    edges = [{'from_node_id':'source','from_output':'text','to_node_id':target,'to_input':'body'}
             for target in ('left','right')]
    received = {}
    async def run(node, inputs):
        frames = [frame async for frame in inputs]
        received[node['id']] = frames
        if node['id'] == 'source':
            yield StreamChunkData(stream_name='text',payload=frames[0].payload,is_last=True,sequence=0)
    await run_streaming_graph('run',nodes,edges,run,initial_inputs={'text':'hello'})
    assert received['source'][0].stream_name == 'value'
    for target in ('left','right'):
        assert received[target][0].payload == b'hello'
        assert received[target][0].stream_name == 'body'
        assert received[target][0].is_last


@pytest.mark.asyncio
async def test_missing_external_input_fails_before_starting_any_plugin():
    async def run(node, inputs):
        raise AssertionError('Plugin must not start')
        yield
    with pytest.raises(DAGValidationError, match='missing'):
        await run_streaming_graph('run',[{'id':'source','input_mapping':[
            {'target_field':'value','source':'input.text'}]}],[],run,initial_inputs={})


@pytest.mark.asyncio
async def test_text_input_markdown_output_business_pipeline():
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    root = Path(__file__).resolve().parents[4]
    saved = {}
    class Storage:
        async def save_artifact(self, **artifact):
            saved[artifact['filename']] = artifact['data']
            return {'file_id': 'artifact-id'}
    definitions = {'input': ('io/text_input', {}),
                   'format': ('format/text_to_md', {'title':'ETL result'}),
                   'output': ('io/text_output', {'filename':'result.txt'})}
    handlers = {}
    for name, (path, parameters) in definitions.items():
        spec = importlib.util.spec_from_file_location('business_' + name,root/'plugins'/path/'src/plugin.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handlers[name] = module.PluginHandler(SimpleNamespace(parameters=SimpleNamespace(**parameters)),Storage())
    nodes = [{'id':name} for name in definitions]
    nodes[0]['input_mapping'] = [{'target_field':'value','source':'input.text'}]
    edges = [dict(from_node_id='input',from_output='text',to_node_id='format',to_input='text_stream'),
             dict(from_node_id='format',from_output='md_stream',to_node_id='output',to_input='text')]
    async def run(node, inputs):
        handler = handlers[node['id']]
        sequences = {}
        def emit(values):
            for port, payload in (values or {}).items():
                sequence = sequences.get(port,0)
                sequences[port] = sequence + 1
                yield StreamChunkData(stream_name=port,payload=payload,sequence=sequence)
        for frame in emit(await handler.on_start()): yield frame
        async for item in inputs:
            if item.payload:
                for frame in emit(await handler.process_buffer(item.payload)): yield frame
        for frame in emit(await handler.on_finish()): yield frame
        for port, sequence in sequences.items():
            yield StreamChunkData(stream_name=port,payload=b'',sequence=sequence,is_last=True)
    await run_streaming_graph('run',nodes,edges,run,initial_inputs={'text':'Данные'})
    assert saved['result.txt'] == saved['notes.md'] == '# ETL result\n\nДанные\n'.encode()
