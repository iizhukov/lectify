"""Authorize one node's capabilities from committed execution and registry data."""
from contextlib import asynccontextmanager
from copy import deepcopy
from sqlalchemy import select

from generated.plugin_manifest import parse_plugin_manifest
from generated.json_data import same_json_data as _same_data
from src.engine.dispatch import guard_execution_write
from src.models import WorkflowExecutionModel, WorkflowNodeExecutionModel, PluginRegistryModel, ContainerAttemptModel


async def assignment_policy(session, *, execution_id, node, ownership, placement):
    if ownership is None or not await guard_execution_write(session,execution_id,ownership):
        raise PermissionError('Assignment lease is not active')
    execution = await session.get(WorkflowExecutionModel,execution_id)
    if execution is None or not execution.user_id:
        raise PermissionError('Assignment owner is unavailable')
    saved = [item for item in execution.graph_json.get('nodes',[]) if item.get('id') == node['id']]
    if len(saved) != 1 or not _same_data(saved[0],node):
        raise PermissionError('Assignment node differs from committed graph')
    node = saved[0]
    row = await session.scalar(select(WorkflowNodeExecutionModel).where(
        WorkflowNodeExecutionModel.execution_id == execution_id,WorkflowNodeExecutionModel.node_id == node['id']))
    version = node.get('plugin_version','0.1.0')
    if (row is None or row.plugin_id != node['plugin_id'] or row.plugin_version != version
            or row.state not in ('PENDING','PROVISIONING','BUFFERING','PROCESSING')):
        raise PermissionError('Assignment node is not active')
    attempt = await session.get(ContainerAttemptModel,placement['attempt_id'])
    if (attempt is None or attempt.execution_id != execution_id or attempt.node_id != node['id']
            or attempt.fence != ownership[1] or attempt.daemon_id != placement['daemon_id']
            or attempt.role != 'plugin' or attempt.state != 'PREPARED'):
        raise PermissionError('Assignment placement does not match active attempt')
    registered = await session.get(PluginRegistryModel,(node['plugin_id'],version))
    if registered is None or not registered.active:
        raise PermissionError('Plugin version is not active')
    manifest,_ = parse_plugin_manifest(registered.manifest_yaml)
    plugin = manifest['plugin']
    if plugin['name'] != node['plugin_id'] or plugin['version'] != version or not plugin['active']:
        raise PermissionError('Registered plugin identity does not match assignment')
    file_ids, prompt_ids = [], []
    if plugin['permissions']['storage']['enabled']:
        file_id = node.get('parameters',{}).get('file_id')
        if file_id:
            if not isinstance(file_id,str) or len(file_id)>128 or '\x00' in file_id:
                raise ValueError('Invalid assigned file ID')
            file_ids.append(file_id)
    if plugin['permissions']['llm']['enabled'] and node.get('prompt_id'):
        prompt_id = node['prompt_id']
        if not isinstance(prompt_id,str) or len(prompt_id)>128 or '\x00' in prompt_id:
            raise ValueError('Invalid assigned prompt ID')
        prompt_ids.append(prompt_id)
    return deepcopy(dict(execution_id=execution_id,node_id=node['id'],owner_id=execution.user_id,
        manifest=manifest,file_ids=file_ids,prompt_ids=prompt_ids,
        parameters=node.get('parameters',{}),initial_inputs=execution.initial_inputs))


def assignment_grants(factory, provision, *, credentials=None):
    @asynccontextmanager
    async def grants(*, placement, execution_id, node, ownership, initial_inputs):
        async with factory() as session:
            policy = await assignment_policy(session,execution_id=execution_id,node=node,
                ownership=ownership,placement=placement)
            if not _same_data(policy['initial_inputs'],initial_inputs):
                raise PermissionError('Assignment inputs differ from committed execution')
            if credentials is not None:
                policy['user_access_token'] = await credentials.load(session,execution_id=execution_id,
                    owner_id=policy['owner_id'],ownership=ownership)
                policy['report_token'] = await credentials.report_capability(session,execution_id=execution_id,
                    owner_id=policy['owner_id'],ownership=ownership)
                policy.update(lease_owner=ownership[0],fence=ownership[1])
            await session.commit()
        async with provision(policy=policy,placement=dict(placement),ownership=ownership) as grant:
            yield grant
    return grants
