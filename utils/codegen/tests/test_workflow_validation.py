from copy import deepcopy
import importlib.util
import sys
from types import SimpleNamespace

import pytest

from config.models import ServiceManifest
from generators.services import base
from generators.services.workflow_validation import WorkflowValidationGenerator


def registry():
    return {'text@1.0.0': {'name': 'text', 'version': '1.0.0', 'active': True,
        'inputs': [{'name': 'in', 'type': 'stream/text'}],
        'outputs': [{'name': 'out', 'type': 'stream/text'}],
        'parameters': [{'name': 'temperature', 'type': 'float', 'default': 0.5}]}}


def graph():
    return {'nodes': [
        {'id': 'a', 'plugin_id': 'text', 'plugin_version': '1.0.0', 'parameters': {}},
        {'id': 'b', 'plugin_id': 'text', 'plugin_version': '1.0.0', 'parameters': {}}],
        'edges': [{'from_node_id': 'a', 'from_output': 'out', 'to_node_id': 'b', 'to_input': 'in'}]}


@pytest.fixture
def validator(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    monkeypatch.setattr(base, 'get_settings', lambda: SimpleNamespace())
    monkeypatch.setattr(base, 'get_context_manager', lambda: SimpleNamespace(get_service_context=lambda name: None))
    manifest = ServiceManifest.model_validate({'service': {'name': 'test_workflow', 'workflow_validation': {'enabled': True}}})
    output = tmp_path / 'generated'
    WorkflowValidationGenerator(manifest, output).generate()
    spec = importlib.util.spec_from_file_location('tested_graph_validator', output / 'workflow_validation/__init__.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_graph_pins_defaults_without_mutating_inputs(validator):
    source = graph()
    schemas = registry()
    before = deepcopy((source, schemas))
    result = validator.validate_graph(source, schemas)
    assert result['nodes'][0]['parameters'] == {'temperature': 0.5}
    assert (source, schemas) == before
    assert validator.validate_graph(result, schemas) == result


@pytest.mark.parametrize('case', ['empty', 'duplicate_id', 'duplicate_edge', 'cycle', 'unknown_node',
    'unknown_port', 'wrong_type', 'unknown_plugin', 'unversioned', 'bool_number', 'unknown_parameter',
    'nonfinite', 'large', 'deep', 'mapping_conflict'])
def test_invalid_graphs_fail(validator, case):
    value, schemas = graph(), registry()
    if case == 'empty': value['nodes'] = []
    elif case == 'duplicate_id': value['nodes'][1]['id'] = 'a'
    elif case == 'duplicate_edge': value['edges'] *= 2
    elif case == 'cycle': value['edges'].append({'from_node_id':'b','from_output':'out','to_node_id':'a','to_input':'in'})
    elif case == 'unknown_node': value['edges'][0]['to_node_id'] = 'unknown'
    elif case == 'unknown_port': value['edges'][0]['from_output'] = 'unknown'
    elif case == 'wrong_type': schemas['text@1.0.0']['inputs'][0]['type'] = 'stream/audio'
    elif case == 'unknown_plugin': schemas = {}
    elif case == 'unversioned': value['nodes'][0]['plugin_version'] = ''
    elif case == 'bool_number': value['nodes'][0]['parameters'] = {'temperature': True}
    elif case == 'unknown_parameter': value['nodes'][0]['parameters'] = {'unknown': 'x'}
    elif case == 'nonfinite': value['nodes'][0]['parameters'] = {'temperature': float('nan')}
    elif case == 'large': value['nodes'] *= 200
    elif case == 'deep':
        schemas['text@1.0.0']['parameters'] = [{'name': 'data', 'type':'dict', 'required':True}]
        value['nodes'][0]['parameters'] = {'data': {}}
        child = value['nodes'][0]['parameters']['data']
        for _ in range(20): child['nested'] = {}; child = child['nested']
    elif case == 'mapping_conflict': value['nodes'][1]['input_mapping'] = [{'target_field':'in','source':'input.file'}]
    with pytest.raises(ValueError): validator.validate_graph(value, schemas)


def test_registry_unavailable_and_corrupt_schema_fail_closed(validator):
    with pytest.raises(validator.RegistryUnavailableError): validator.validate_graph(graph(), None)
    bad = registry(); bad['text@1.0.0']['version'] = '2.0.0'
    with pytest.raises(validator.RegistryUnavailableError): validator.validate_graph(graph(), bad)


def test_corrupt_registry_identifiers_are_backend_failures(validator):
    bad = registry()
    bad['text@1.0.0']['inputs'][0]['name'] = []
    with pytest.raises(validator.RegistryUnavailableError):
        validator.validate_graph(graph(), bad)
    bad = registry()
    bad['text@1.0.0']['parameters'][0]['name'] = ''
    with pytest.raises(validator.RegistryUnavailableError):
        validator.validate_graph(graph(), bad)
