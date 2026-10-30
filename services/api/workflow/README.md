# Workflow service

`workflow.v1.WorkflowService` stores workflow and reusable node templates and
creates immutable snapshots for the separate execution API. It does **not** queue
or start work and never returns a simulated execution ID.

The generated user-auth interceptor supplies `lectify_principal`; raw owner/admin
headers are ignored. Owners can edit their own records, administrators can manage
global records, public workflows/global templates can be read and forked by
signed-in users. Administrators do not gain blanket access to private user data.
No request accepts a caller-selected owner. Updates/deletes require a positive
`expected_version`; a losing concurrent edit gets ABORTED instead of overwriting
another edit. Full update messages replace mutable fields, rather than applying
ambiguous protobuf default-value patches.

The RPC contract includes workflow CRUD/list, reusable node CRUD/list, fork,
CreateSnapshot and GetSnapshot. Publishing is a versioned workflow update setting
`is_public`; global resources are administrator-owned. Node definitions retain
name, description, plugin version, parameters, named inputs, prompt ID and explicit
external-input mappings. Legacy node-to-node edges must be migrated to explicit
named ports; raw expression transforms are not executed or silently accepted.

## Graph policy in codegen

`workflow_validation.enabled: true` generates
`generated.workflow_validation.validate_graph(graph, registry_schemas)`. This
shared validator contains topology/transport validation; `src/` contains ownership
and persistence logic. Registry keys are `plugin_id@version`; values are active
plugin manifest records with `name`, `version`, `inputs`, `outputs`, `parameters`.

The helper requires pinned active plugin versions, validates named ports and exact
port types, rejects duplicate node IDs/edges, multiple producers for a single input,
cycles and conflicting external/edge bindings. Typed parameters reject unknown
fields, bool-as-number, nonfinite values and excessive size/depth. Defaults are
copied into a canonical graph so snapshots do not depend on later manifest defaults.
Bounds: 256 nodes, 1024 edges, 1 MiB graph, 64 KiB parameters per node, JSON depth
12, arrays/objects up to 256 elements and strings up to 8192 characters. Workflow
names/descriptions are bounded separately. Present edges/mappings are validated;
unbound inputs are allowed in templates and must be supplied/checked by execution.

`WorkflowServiceImpl(registry_provider=...)` accepts a callable returning an
immutable registry snapshot for the graph, synchronously or asynchronously
(async calls have a five-second deadline). The **same real generated validator**
always enforces it. A missing registry provider returns UNAVAILABLE for mutations
and snapshot/fork creation. There is no production fake registry or registry-bypass
flag. Connecting this hook to the approved plugin catalog remains deployment work.
Prompt IDs remain references; the prompt service must enforce its ACL when they
are resolved by the agent/provider.

## Snapshots

CreateSnapshot copies the authorized template/version into a caller-owned row,
with a content SHA-256 and immutable graph. A per-caller `request_key` provides
idempotency; reuse for a different template/version is rejected. Template updates,
unpublishing and deletion do not change an already authorized snapshot. Snapshots
have no FK to the deletable template and have no update/delete RPC. Other users
cannot read them. After awaiting registry validation, snapshot/fork creation
rechecks source version and visibility under a database write lock; a concurrent
unpublish/edit cannot create a stale authorized copy.

The execution service must consume this snapshot contract rather than reread a
mutable workflow. It still owns queueing, run ownership, node states, artifacts,
cancellation and history; these are not duplicate responsibilities of workflow.

## Verification

```sh
python3 -m pytest services/api/workflow/tests -q
python3 -m pytest utils/codegen/tests/test_workflow_validation.py -q
```

Tests generate isolated temporary service/protobuf/validator/user-auth modules and
use real SQLite persistence. The gRPC test uses the real generated user-auth
interceptor with a deterministic test verifier, checking that spoofed owner/admin
headers do not alter identity. It is not a live auth deployment test. Tests also
cover optimistic concurrent updates, immutable/idempotent snapshots, visibility
races, global/owner ACL, malformed graphs and upgrade/downgrade schema parity.
They require no `.env`, preexisting ignored generated checkout, Docker, API key or
paid requests. The local RPC test needs loopback bind permission in restricted
sandboxes. PostgreSQL concurrency and the full registry/auth/execution deployment
remain integration gates.
