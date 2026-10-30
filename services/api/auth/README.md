# Auth service

`auth.v1.AuthService` owns credentials, account identifiers and session state.
`api_auth` listens on gRPC port 10021. User profile/personal data will be exposed
through the separate profile/personal services; they must reference this stable
user ID rather than create a second password store.

Register/Login return distinct opaque access (15 minutes) and refresh (7 days)
tokens. Only SHA-256 token hashes are persisted. Refresh atomically consumes the
old session and creates a replacement in one database transaction. Logout accepts
either token and revokes both. Password change/reset increments a persistent
security version and invalidates every old session, including a racing login or
refresh that read the previous credentials. No trust is placed in caller-supplied
user ID or admin headers; `Authenticate(access_token)` is the verified principal
boundary for generated user-auth interceptors. Invalid credentials use the same
UNAUTHENTICATED error. Registration conflict is ALREADY_EXISTS.

Passwords use salted PBKDF2-HMAC-SHA256 (600,000 iterations) through `to_thread`,
with a 12–1024 character policy. An absent username performs a dummy verification.
The deployment gateway must still provide request limits, TLS and auth throttling;
password hashing is deliberately expensive and is not a substitute for limits.

## Password-reset delivery

Public reset requests enqueue database state only. They never await a mail/API
adapter, so provider latency and errors cannot identify existing accounts. Existing
and unknown addresses get the same `accepted=true`, which never claims mail was
sent. At most one outstanding reset per account is enqueued. Reset hashes and a
separate durable outbox are committed together.

The outbox holds **Fernet ciphertext**, not a plaintext credential. Its key must
be supplied separately from the database, for example from Vault. Inject the same
`reset_delivery_key` and async `reset_delivery(email, token)` adapter into all auth
service/worker instances. Do not write a key into manifests, source or migrations.
Without both, RequestPasswordReset returns UNAVAILABLE for every address. There
is no built-in fake email sender and no production delivery provider configured.

The worker calls `deliver_password_resets(limit=100, timeout=20,
lease_seconds=30)`. Claims use conditional database updates with owner IDs and
leases. A cancelled worker's lease expires and another replica can retry. Provider
calls have a bounded timeout; the lease must exceed that timeout by five seconds.
Delivery is at-least-once, so an external provider must tolerate duplicate mail
with the same one-use token after an ambiguous crash. Failures preserve ciphertext
for delayed retry (60 seconds, up to eight attempts); they return counts without
provider exception text. Successful delivery wipes ciphertext. Expired or consumed
resets cannot be delivered. Password reset/change removes matching delivery rows.
Key rotation requires draining/discarding pending ciphertext or preserving access
to the previous key until its reset TTL expires; a wrong key fails closed.

A generated lifecycle/scheduler integration must wire the chosen delivery adapter,
Vault key and worker invocation before enabling password reset in the public UI.
The delivery method is business logic, not a self-started process or detached task.
Periodic retention cleanup and delivery/attempt monitoring also need deployment
wiring. No infrastructure startup code lives in `src/`.

## Verification

```sh
python3 -m pytest services/api/auth/tests -q
```

Tests copy source/proto into a temporary project and generate actual DB/gRPC
modules there; existing ignored `generated/`, repository `.env`, Docker and paid
APIs are unnecessary. SQLite tests cover migrations, persisted users and sessions,
independent service replicas, concurrent refresh replay, expiry, one-use resets,
wrong-password rejection, ciphertext/key separation, cancelled-worker lease
recovery, retries, timeout and callback independence from public requests. One
loopback gRPC test checks actual RPC authentication/error behavior (requires
permission to bind 127.0.0.1 in restricted sandboxes). PostgreSQL isolation and
full gateway/service deployment remain release checks, not claims made by these
tests.
