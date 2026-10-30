# Prompt service

`api_prompt` owns user prompt templates and administrator-managed global templates.
The protobuf contract provides CRUD, deterministic paginated listing and safe literal
`{{variable}}` rendering. System and user templates can be updated independently;
optional protobuf fields distinguish omission from clearing a field. Update/delete
require `expected_version`; concurrent writers receive `ABORTED` and reload.

A verified, server-populated `context.lectify_principal` must expose `user_id` and
`is_admin`. Request fields never select an owner. Raw `x-user-id` metadata is ignored.
The `user_auth.enabled` manifest setting installs the generated interceptor: it sends
`x-user-authorization: Bearer <access token>` to `api_auth.Authenticate` and attaches
only the verified result. Missing/invalid sessions fail closed with `UNAUTHENTICATED`;
auth backend errors/timeouts return `UNAVAILABLE`. Positive sessions are not cached. Service tickets alone authenticate the calling service,
not the end user. Global prompts are readable to authenticated users; only admins can
create/change/delete them. Private prompts are visible/writable only to the owner,
including list/render; inaccessible IDs return `NOT_FOUND` to avoid disclosure.

Templates use single-pass literal substitution, not Python/Jinja evaluation. Variables
must be declared, unique ASCII identifiers; rendering requires exactly those variables.
The service bounds stored and rendered text and checks expansion length before allocating
it. Values are never rendered recursively. HTML escaping belongs to the eventual UI
consumer; rendered content is text, not executable markup.

Infrastructure is generated from `service.yaml`; `src/` contains ownership policy,
persistence models and prompt operations. `migrations/versions/0001_add_prompts.py`
creates the persistent schema. Existing codegen's migrations CLI manages upgrade/downgrade.
No handwritten HTTP server or database connection wrapper belongs here.

Run `python3 -m pytest services/api/prompt/tests -q` from the repository root. The test
creates temporary generated modules and SQLite DB, applies the real migration, starts
loopback gRPC and exercises CRUD/render, ACL, pagination, stale/concurrent versions,
replica reads, bounded expansion and downgrade. It needs local socket permission, Python
runtime test dependencies (pytest, grpcio-tools, SQLAlchemy, aiosqlite, alembic,
pydantic-settings, structlog) and no external API/database/credentials.

Open integration gates: gateway HTTP compatibility,
initial global seed prompts, PostgreSQL/container tests and deployment/network identity.
