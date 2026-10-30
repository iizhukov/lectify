# Plugin assignment agent

`service.plugin_agent.enabled` generates the shared plugin protobuf contract,
scoped/mTLS listener and complete `PluginAgentService` proxy. `src/policy.py`
contains immutable assignment capabilities derived from the plugin manifest;
`src/service.py` composes these with injected asynchronous backend ports.

Startup requires `LECTIFY_AGENT_TOKEN`, `EXECUTION_ID`, `NODE_ID` and
`LECTIFY_AGENT_ASSIGNMENT_FILE` (trusted controller-provisioned JSON containing
execution_id, node_id, owner_id, plugin manifest, file_ids, prompt_ids and a delegated
user_access_token plus lease_owner, positive fence and secret report_token). The file must be regular, not a symlink, with private permissions
(0400/0600); mount it only into the agent, never into the untrusted plugin container.
The JSON is not accepted from plugin RPCs. The assignment must match the listener
scope. Default listener is loopback `127.0.0.1:50055`; remote listeners require all
`LECTIFY_AGENT_TLS_CERT_FILE`, `LECTIFY_AGENT_TLS_KEY_FILE`, and
`LECTIFY_AGENT_TLS_CA_FILE`. Bearer and execution headers are checked for every RPC.

Model/purpose, file/prompt IDs and artifact names default to deny. Owner identity
comes only from the assigned policy and is passed separately to each backend;
plugins cannot choose an owner in their request. Streaming audio/artifacts are
bounded and metadata-first; provider failures never become fabricated successes.

Backend ports are asynchronous `call_llm`, `transcribe`, `read_file`,
`fetch_prompt`, `save_artifact`, `report_progress`, `report_metrics` and `log`.
They receive owner_id/execution_id/node_id plus validated business fields.
CallLLM and ReadFile return async iterators; remaining methods return awaitables.
Artifacts must return actual file_id and exact size_bytes after persistence.

Generated RPCBackends calls actual auth/file/prompt/provider services. Every
operation authenticates the delegated access token and checks its principal
against the assigned owner, then forwards the user credential to existing ACLs.
The credential expires/revokes normally; renewal/delegation for jobs longer than
its lifetime remains an orchestration responsibility. Service authentication
uses TAS. Remote backend and TAS channels require mTLS with
LECTIFY_AGENT_BACKEND_TLS_CERT_FILE/KEY_FILE/CA_FILE; plaintext is local-only.
Addresses may be configured with LECTIFY_AGENT_AUTH_ADDRESS, FILE_ADDRESS,
PROMPT_ADDRESS, PROVIDER_ADDRESS, ORCHESTRATOR_ADDRESS and TAS_ADDRESS (each with LECTIFY_AGENT_ prefix).

Progress/metrics/log RPCs call the durable ReportNodeEvent receiver with an
assignment-bound worker lease owner, fence and report capability. They acknowledge
only an accepted matching event ID. The orchestrator must provision that capability;
missing credentials fail startup rather than fabricate acknowledgements.
No container launch, assignment distribution, durable ownership, start/cancel/status
command plane or production worker readiness is claimed yet. STT adapters require
an explicit supported audio MIME or recognized encoded-audio signature. Current
full-file STT works only within runtime/provider size limits; arbitrarily cutting
compressed container bytes is not supported audio segmentation.
