import json
import pytest

from generated.plugin_manifest import parse_plugin_manifest
from src.engine.assignment_envelope import AssignmentEndpoints, build_assignment_grant
from src.engine.deployment import configured_dispatcher
from src.engine.runtime_dispatcher import RuntimeStreamDispatcher


def policy():
    manifest, _ = parse_plugin_manifest('plugin: {name: custom, language: rust}')
    return dict(execution_id='run',node_id='node',owner_id='alice',lease_owner='replica',fence=1,
        credential_expires_at=2000,user_access_token='la_verified',report_token='r'*48,
        manifest=manifest,parameters={'answer':42})


def endpoints():
    return AssignmentEndpoints(agent='127.0.0.1:50055',runtime='127.0.0.1:50056',
        backends={name:'127.0.0.1:10000' for name in ('auth','file','prompt','provider','orchestrator','tas')})


def test_custom_program_receives_parameters_without_privileged_credentials():
    grant = build_assignment_grant(policy(),endpoints(),clock=lambda:1000,
        runtime_command=['/runtime/custom-program'],runtime_cwd='/runtime')
    assignment = json.loads(grant['environment']['LECTIFY_AGENT_ASSIGNMENT_JSON'])
    assert assignment['runtime_command'] == ['/runtime/custom-program']
    assert assignment['runtime_environment']['LECTIFY_RUNTIME_TOKEN'] != grant['environment']['LECTIFY_AGENT_CONTROL_TOKEN']
    assert 'la_verified' not in json.dumps(assignment['runtime_environment'])
    assert 'r'*48 not in json.dumps(assignment['runtime_environment'])
    assert json.loads(grant['runtime']['control']['parameters_json']) == {'answer':42}
    assert 'manifest' not in assignment and len(assignment['manifest_sha256']) == 64


def test_expired_assignment_and_relative_program_are_rejected():
    with pytest.raises(ValueError):
        build_assignment_grant(policy(),endpoints(),clock=lambda:2000)
    with pytest.raises(ValueError):
        build_assignment_grant(policy(),endpoints(),clock=lambda:1000,runtime_command=['relative'])


def test_deployment_selects_remote_workers_without_contacting_docker(tmp_path):
    config = {'workers':{'daemon-a':{'endpoint':'127.0.0.1:10042'}},
              'plugins':[{'id':'custom','version':'0.1.0','image':'sha256:'+'a'*64}]}
    path = tmp_path/'deployment.json'
    path.write_text(json.dumps(config))
    dispatcher = configured_dispatcher(lambda:None, object(),path)
    assert isinstance(dispatcher,RuntimeStreamDispatcher)
    identity, worker = dispatcher.workers.choose('run','node','plugin')
    assert identity == 'daemon-a' and worker.endpoint == '127.0.0.1:10042'
    with pytest.raises(ValueError,match='credential key'):
        configured_dispatcher(lambda:None,None,path)
