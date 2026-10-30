# File service

`api_file` owns uploaded file metadata and object lifecycle. Generated gRPC, user-auth,
DB and S3 modules supply infrastructure. Every operation requires a verified user principal;
raw user-id headers are ignored. Files are private to their owner, including list/download;
unknown and inaccessible IDs both return `NOT_FOUND`. Public service API exposes file IDs,
not buckets or object keys. Display filenames cannot contain paths/control characters.
Object keys use server-generated UUIDs only.

Upload is a bounded client stream. Frame zero contains metadata; data frames start at
sequence 1, increase monotonically and end with explicit `is_last=true`. Stream completion
alone is insufficient. Declared size must match the complete body, at most 256 MiB; chunks
are at most 64 KiB, SHA256 optionally checks the declared checksum. The overall incoming
stream deadline is 300 seconds. A temporary spool uses at most 1 MiB before spilling to disk;
no full upload/download payload is materialized by service code. Download sends metadata,
64 KiB chunks and a final EOF only after validating size and checksum. A consumer must not
accept a partial download as complete.

Object-client operations run in worker threads. Cancellation waits for a worker before
closing its file/response; cancelled/failed uploads attempt object and metadata cleanup.
Objects are first recorded as `PENDING` and become readable only after storage succeeds.
Deletion persists `DELETING` before removing the object; a failed delete is invisible to
reads and can be retried by its owner. Cleanup failure or process crash can leave a durable
`PENDING`/`DELETING` record. Automatic crash reconciliation/leases and quotas are remaining
integration gates; this service does not pretend DB and S3 share an atomic transaction.

The generated S3 adapter supports seekable uploads, response streaming and idempotent
object delete, with finite connect/read socket timeouts and limited retries. Synchronous
boto3 does not provide a strict overall wall-clock timeout for an entire large transfer.
Storage credentials/bucket setup come from generated settings and infrastructure manifests.

`python3 -m pytest services/api/file/tests -q` performs fresh temporary codegen, applies
and rolls back the actual migration, starts real loopback Auth/File gRPC servers, and uses
SQLite plus an **in-memory object-store test double**. Tests cover ownership, upload bounds,
protocol errors, integrity, empty files, slow senders, storage failure, cancellation cleanup
and retry deletion. No external credentials/API are required. Real MinIO, PostgreSQL,
container deployment, crash recovery and the eventual HTTP gateway still need integration
verification. Codegen separately tests generated boto3 forwarding/response closure against
fake calls in `utils/codegen/tests/test_s3_stream.py`.
