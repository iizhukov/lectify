# Plugin assignment agent

`service.plugin_agent.enabled` generates the shared plugin protobuf contract,
scoped/mTLS listener and complete `PluginAgentService` proxy. `src/policy.py`
contains immutable assignment capabilities derived from the plugin manifest;
`src/service.py` composes these with injected asynchronous backend ports.

Startup requires `LECTIFY_AGENT_TOKEN`, `EXECUTION_ID`, `NODE_ID` and
`LECTIFY_AGENT_ASSIGNMENT_FILE` (trusted controller-provisioned JSON containing
execution_id, node_id, owner_id, plugin manifest, file_ids and prompt_ids).
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

Deployment wiring of provider/file/prompt/progress clients remains required.
The default UnconfiguredBackends deliberately returns UNAVAILABLE for RPCs rather
than fake data. No container launch, assignment distribution, durable ownership,
start/cancel/status command plane or production worker readiness is claimed yet.
