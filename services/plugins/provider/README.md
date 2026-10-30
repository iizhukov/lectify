# Polza provider service

`plugins_provider` translates bounded chat/audio RPCs into the Polza HTTP API.
Generated code owns the gRPC server, TAS service authentication, pooled HTTP client,
TLS verification, transport timeouts, environment settings and shutdown. Business source
owns model/purpose policy, request validation, SSE completion and audio adaptation.

The self-contained protocol is `proto/plugins/provider/index.proto`: `CallLLM` matches
plugin-agent message fields and adds owner/execution/node context. `Transcribe` accepts
metadata first, monotonically sequenced <=64 KiB audio chunks, explicit EOF and an exact
declared size. The adapter sends bounded JSON/base64 chunks, not speculative multipart.
Only supported audio MIME types are accepted; caller-supplied external URLs are never used.

Production endpoint is fixed to `https://polza.ai/api/v1`. Redirects, environment proxies,
unverified TLS and caller extra parameters are disabled. A numeric-loopback HTTP endpoint
can only be injected by test code. Credentials come from generated SecretStr settings:
`PLUGINS_PROVIDER_HTTP_BEARER_TOKEN`, provisioned by Vault/environment, never YAML/source.
Do not log or print Settings credentials. No live API key or paid request was used in tests.

`extensions.provider` contains the business policy; generated `Settings.extensions` exposes
manifest defaults with an optional `PLUGINS_PROVIDER_EXTENSIONS` JSON override. An absent
policy denies every model and purpose. The checked-in manifest explicitly allows a small
chat model and mini transcription model; operators can replace the allowlist/defaults.
Limits include input/output bytes, token request cap, audio <=8 MiB, total request deadline
(including waiting for a concurrency slot) and per-instance concurrency. These are bounded
requests, **not a distributed monetary quota**. Cluster-wide billing quotas and admission
control remain a separate integration gate.

Chat accepts text roles only. SSE frames are parsed across arbitrary byte boundaries with
wire-byte/event limits. EOF without both a natural `stop` and `[DONE]` is failure. Provider
quota errors, malformed/truncated data, token-limit finishes and timeouts never emit a
successful terminal frame. Usage is returned only after complete success. HTTP requests
are not automatically retried because the provider may already have charged them.

Audio is spooled after 1 MiB and streamed as JSON data-URL base64 without loading the whole
encoded body into memory. Size is capped below the documented approximate HTTP body limit.
This implementation supports synchronous text transcription models; async Aiesa jobs,
diarization and word timestamps are not implemented. Large recordings must be segmented
by the media pipeline. The generated HTTP helper settles blocking file operations before
cancellation unwinds the caller's temporary resources.

`python3 -m pytest services/plugins/provider/tests -q` creates a fresh temporary generated
service, runs real loopback gRPC plus a real local HTTP/SSE fixture, and verifies complete
chat/transcription requests, byte-boundary parsing, allowlists, quota/redirect/timeout,
truncated/malformed/oversized responses, EOF checks, cancellation and pooled-client cleanup.
The fixture uses a fake token and no external API/storage. Real Polza, TLS deployment,
provider capacity and cross-replica quotas still require separate verification. Production
TAS policies must restrict ProviderService to the agent/backend callers allowed to spend.

Official API sources consulted (2026-10-30):

- [Polza chat guide](https://github.com/polza-ai/docs/blob/main/gaidy/chat-completions.mdx)
- [Chat API reference](https://github.com/polza-ai/docs/blob/main/api-reference/chat/completions.mdx)
- [Audio transcription reference](https://github.com/polza-ai/docs/blob/main/api-reference/audio/transcriptions.mdx)

The official transcription reference documents JSON `file` as base64/data URL and a
roughly 15 MB body limit; this implementation caps raw audio at 8 MiB. It identifies
`openai/gpt-4o-mini-transcribe` as a lower-cost transcription option. Model availability
and prices can change; the manifest is an explicit configurable allowlist, not a pricing
or availability guarantee.
