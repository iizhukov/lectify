# Generated gRPC transport

Services opt in with `service.grpc_transport.enabled: true`. This is enabled for
the active API, orchestrator, provider, config and TAS services. Plugin sidecars
retain their assignment-specific TLS configuration.

Server credentials use `LECTIFY_GRPC_SERVER_TLS_CERT_FILE`,
`LECTIFY_GRPC_SERVER_TLS_KEY_FILE` and `LECTIFY_GRPC_SERVER_TLS_CA_FILE`.
All three are required together. With credentials, the generated listener
requires a client certificate signed by the configured CA. Without credentials,
the default listener binds only to loopback. `LECTIFY_GRPC_LISTEN_ADDRESS` can
override the listener; remote plaintext addresses are rejected.

Clients use the corresponding `LECTIFY_GRPC_CLIENT_TLS_CERT_FILE`,
`LECTIFY_GRPC_CLIENT_TLS_KEY_FILE` and `LECTIFY_GRPC_CLIENT_TLS_CA_FILE`.
Remote endpoints require mTLS. Loopback and Unix sockets support local plaintext
development. Server-name verification stays enabled; no hostname override or
fallback to plaintext is configured. TAS/config direct clients follow the same
policy; optional address overrides are `LECTIFY_TAS_ADDRESS` and
`LECTIFY_CONFIG_ADDRESS`.

Docker service names containing underscores are supported for TLS endpoints.
Certificate SANs must match the actual service alias. The optional sandbox
`network_aliases` are bounded argument values for a selected named network;
aliases cannot be configured with network `none`. TAS dependencies and ports
come from `ticket_auth.tas_service` and its manifest, including protobuf imports.

Transport authentication supplements TAS service authorization and revocable
user authentication. It does not replace either policy. Provisioning certificates,
Vault delivery and deploying the full service chain are separate deployment work.

`utils/codegen/tests/test_service_tls.py` creates temporary test certificates and
checks a real generated client/server exchange, client-certificate enforcement,
hostname rejection, refusal of remote plaintext, and shutdown cancellation.
`utils/integration/service_tls_docker.py` tests two containers on a disposable
internal network: the matching `api_auth` SAN succeeds while another alias to
the same server is rejected. Its certificates are temporary test credentials;
the test is not certificate provisioning for the application deployment.

Read-only workloads can supply each TLS prefix with `_CERT_PEM`, `_KEY_PEM`
and `_CA_PEM` instead of the three `_FILE` variables. A complete source is
required; mixed, empty or partial sources fail closed. Inline fields are ASCII
and limited to32KiB each. Credentials are loaded into memory and omitted from
configuration repr; no key file is written. This applies to generic services,
scoped plugin/agent servers, sidecar clients and TAS/config clients.
Docker daemon administrators can inspect container environment; same-UID
process isolation and production certificate issuance remain separate work.
The Docker DNS integration now supplies PEM environment credentials and keeps
all CA/leaf private keys outside its build context.
