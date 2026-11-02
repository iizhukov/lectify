"""Compose host agents and scoped plugin runtimes from operator configuration."""
from contextlib import asynccontextmanager
import os
from pathlib import Path

from generated.docker_sandbox import DockerSandbox
from generated.docker_workers import DockerWorkers
from generated.transport import TLSConfig
from src.engine.assignment_envelope import AssignmentEndpoints, AssignmentTLS, build_assignment_grant
from src.engine.assignments import runtime_assignments
from src.engine.grants import assignment_grants
from src.engine.remote_worker import RemoteWorker
from src.engine.runtime_dispatcher import RuntimeStreamDispatcher


def configured_dispatcher(factory, credentials, path=None):
    path = path or os.environ.get('LECTIFY_DEPLOYMENT_FILE')
    if not path:
        return None
    if credentials is None:
        raise ValueError('Execution credential key is required for container deployment')
    raw = Path(path).read_bytes()
    if len(raw) > 1048576:
        raise ValueError('Deployment configuration exceeds limit')
    from generated.json_data import parse_json_object
    config = parse_json_object(raw.decode(), max_bytes=1048576)
    inventory = config['workers']
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError('Explicit host agent inventory required')
    workers = DockerWorkers({identity: RemoteWorker(record['endpoint'])
        for identity, record in inventory.items()})
    images, runtimes = {}, {}
    for record in config['plugins']:
        key = (record['id'], record['version'])
        if key in images:
            raise ValueError('Duplicate plugin image binding')
        images[key] = record['image']
        runtimes[key] = record
    tls_records = config.get('tls', {})
    tls = AssignmentTLS(**{role: TLSConfig.from_files(**files)
        for role, files in tls_records.items()})

    @asynccontextmanager
    async def provision(*, policy, placement, ownership):
        worker = inventory[placement['daemon_id']]
        name = DockerSandbox.name(policy['execution_id'], policy['node_id'], ownership[1])
        endpoints = AssignmentEndpoints(
            agent=worker['agent_endpoint'].format(name=name),
            runtime=worker['runtime_endpoint'].format(name=name),
            backends=config['backends'], agent_listen=worker.get('agent_listen', '0.0.0.0:50055'),
            runtime_listen=worker.get('runtime_listen', '0.0.0.0:50056'),
            sidecar=worker.get('sidecar', '127.0.0.1:50055').format(name=name),
            network=worker['network'], aliases=tuple(alias.format(name=name)
                for alias in worker.get('network_aliases', [name])))
        plugin = policy['manifest']['plugin']
        runtime = runtimes[(plugin['name'], plugin['version'])]
        grant = build_assignment_grant(policy, endpoints, tls=tls,
            runtime_command=runtime.get('command'), runtime_cwd=runtime.get('cwd','/runtime'))
        timeout=runtime.get('runtime_timeout',300)
        if type(timeout) not in (int,float) or not 0<timeout<=3600:
            raise ValueError('Invalid trusted runtime timeout')
        grant['runtime']['timeout']=timeout
        if 'manifest_file' in runtime:
            manifest_file = runtime['manifest_file']
            if not isinstance(manifest_file,str) or not manifest_file.startswith('/') or '\x00' in manifest_file:
                raise ValueError('Plugin manifest path must be absolute')
            grant['environment']['LECTIFY_AGENT_PLUGIN_MANIFEST_FILE'] = manifest_file
        yield grant

    grants = assignment_grants(factory, provision, credentials=credentials)
    dispatcher = RuntimeStreamDispatcher(runtime_assignments(factory, workers, images, grants))
    dispatcher.workers = workers
    return dispatcher
