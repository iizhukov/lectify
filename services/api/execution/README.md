# Execution API

`StartWorkflow` creates an immutable caller-owned workflow snapshot, then starts
the orchestrator with a stable UUID derived from the caller and snapshot IDs.
Retry using the same workflow version, request key and inputs. Conflicting inputs
are rejected by the orchestrator's execution-ID contract. The orchestrator's
`workflow_id` stores the immutable snapshot reference for executions started here.

`GetStatus`, `Cancel` and `StreamEvents` forward the verified user credential;
backend ACLs remain authoritative. A stream session has a bounded deadline and
can resume using `after_sequence`. Sequence-zero state snapshots do not advance
that cursor. No owner, backend address or executable command comes from the API
request.

Transport, TAS authentication, user verification, channel lifecycle and the
service entrypoint are generated from `service.yaml`. This service has no local
database or independent execution-state projection.

Tests currently inject backend stubs and exercise snapshot ownership/version,
stable IDs, typed configuration, forwarding, deadlines and resource cleanup.
They do not prove a deployed workflow/API/orchestrator chain. Production TLS,
container assignment, durable payload replay and the remaining monolith parity
gates are still required for a complete deployment.
