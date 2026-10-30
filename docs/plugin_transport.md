# Plugin runtime transport

Codegen generates `generated.server`, `generated.runtime`, `generated.transport` and
`generated.sidecar_client`. Docker plugin images start in `PLUGIN_MODE=server`.
Local direct execution defaults to `PLUGIN_MODE=pipe`; select `server` explicitly
when mounting the generated runtime as a service.

## Runtime listener

Set `LECTIFY_RUNTIME_TOKEN`, `EXECUTION_ID` and `NODE_ID`. Every RPC, including
health, requires `authorization: Bearer <token>`, `x-execution-id` and `x-node-id`.
Execution identity is fixed when the runtime is constructed; later environment
changes cannot redirect handler or sidecar identity. Credentials must be provisioned
by the assigning agent, never bundled in a plugin manifest or image.

`LECTIFY_RUNTIME_ENDPOINT` defaults to `127.0.0.1:50056`. Without TLS, only loopback
or an absolute `unix:/path/to/socket` endpoint is accepted. For a remotely reachable
listener, provision all three PEM files:

- `LECTIFY_RUNTIME_TLS_CERT_FILE`: server certificate chain;
- `LECTIFY_RUNTIME_TLS_KEY_FILE`: matching private key;
- `LECTIFY_RUNTIME_TLS_CA_FILE`: CA roots trusted for **client** certificates.

All three must be set together. Files are loaded before binding. The generated
server calls `grpc.ssl_server_credentials(..., require_client_auth=True)` and
`add_secure_port`; it never downgrades to plaintext if TLS is configured incorrectly.
The bearer token and execution scope are still required after a successful TLS
handshake. A valid client certificate alone does not authorize an execution.

## Plugin → agent client

`LECTIFY_AGENT_ENDPOINT` defaults to `localhost:50055`. Plaintext connections are
restricted to local loopback/Unix endpoints. For remote connections set all of:

- `LECTIFY_AGENT_TLS_CERT_FILE`: plugin client certificate chain;
- `LECTIFY_AGENT_TLS_KEY_FILE`: client private key;
- `LECTIFY_AGENT_TLS_CA_FILE`: CA roots trusted for the agent server certificate.

`LECTIFY_AGENT_TOKEN` supplies the agent bearer token independently of the runtime
listener token. The receiving agent must enforce its own client and execution policy.
No TLS server-name override or certificate-verification bypass is exposed. Use an
endpoint hostname/IP present in the server certificate SAN.

The shared helper `generated.transport.create_channel(endpoint, tls)` is also usable
by a caller connecting to the plugin runtime; construct `TLSConfig.from_files(cert,
key, ca)` and provide the runtime authorization metadata above. `SidecarAgentClient`
accepts an explicit `tls=TLSConfig(...)` or loads its dedicated environment settings.
Client and server gRPC messages are limited to 2 MiB; runtime payload limits apply
separately. Application-level RPC deadlines remain in effect with TLS.

Provision private keys as read-only secret mounts with restricted permissions.
Certificate/key rotation currently requires restarting the process; dynamically
reloading trust roots is not implemented. Unix socket parent directories must be
managed by the agent. No remote cluster deployment, service discovery or PKI issuer
is automatically installed by this transport module.

## Verification

`python3 -m pytest utils/codegen/tests/test_plugin_tls.py -q` creates temporary
OpenSSL CA/server/client certificates and exercises real loopback mTLS. It checks
trusted client success, refusal of missing/untrusted client certificates, untrusted
server roots, continued bearer authentication, incomplete TLS configuration and
remote plaintext refusal. It makes no external network or paid API requests.
