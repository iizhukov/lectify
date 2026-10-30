import json

import pytest
from generated.protos.server import index_pb2 as pb
from src.service import _node_data


def test_frozen_node_configuration_preserves_json_types_and_bindings():
    parameters = {'enabled':True,'count':3,'temperature':0.5,'options':{'key':['value',None]}}
    mappings = [{'target_field':'file_id','source':'workflow.input.file','transform':'identity'}]
    node = pb.WorkflowNode(id='node',plugin_id='plugin',parameters_json=json.dumps(parameters),
        input_mapping_json=json.dumps(mappings),prompt_id='prompt')
    result = _node_data(node)
    assert result['parameters'] == parameters
    assert result['input_mapping'] == mappings and result['prompt_id'] == 'prompt'


@pytest.mark.parametrize('raw', ['[]','{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}','{"x":1e999}'])
def test_invalid_typed_parameters_are_rejected(raw):
    with pytest.raises(ValueError):
        _node_data(pb.WorkflowNode(id='node',plugin_id='plugin',parameters_json=raw))


def test_legacy_default_shape_is_preserved_for_idempotency():
    legacy = _node_data(pb.WorkflowNode(id='node',plugin_id='plugin',parameters={'model':'simple'}))
    typed = _node_data(pb.WorkflowNode(id='node',plugin_id='plugin',parameters_json='{"model":"simple"}',
        input_mapping_json='[]'))
    assert legacy == typed
    with pytest.raises(ValueError):
        _node_data(pb.WorkflowNode(parameters={'x':'value'},parameters_json='{}'))
