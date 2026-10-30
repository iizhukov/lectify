"""Assignment policy composition; network/transport/proxy are generated."""
from generated.plugin_agent.proxy import PluginAgentProxy
from src.policy import AssignmentPolicy


def create_agent(assignment, backends=None):
    policy = AssignmentPolicy.from_manifest(
        execution_id=assignment['execution_id'], node_id=assignment['node_id'],
        owner_id=assignment['owner_id'], manifest=assignment['manifest'],
        file_ids=assignment.get('file_ids', ()), prompt_ids=assignment.get('prompt_ids', ()),
    )
    if backends is None:
        from generated.plugin_agent.backends import RPCBackends
        backends = RPCBackends(assignment['user_access_token'], lease_owner=assignment['lease_owner'],
                               fence=assignment['fence'], report_token=assignment['report_token'])
    return PluginAgentProxy(policy, backends)
