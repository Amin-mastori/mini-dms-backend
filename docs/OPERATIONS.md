# Operations and failure diagnosis

## Start from evidence

1. Save the response status, safe error code and `X-Request-ID`.
2. Identify the document UUID and current revision/status.
3. Inspect service state with `docker compose ps -a`.
4. Correlate API/dispatcher/worker logs using the request ID.
5. Inspect `/api/v1/admin/jobs/?request_id=<uuid>` as an administrator.

Never copy authorization headers, `.env`, full request bodies, file contents or
private storage credentials into support logs. `docker compose config --quiet`
validates configuration without printing expanded secrets.

```bash
docker compose logs --tail=200 api worker dispatcher
docker compose exec worker tesseract --list-langs
docker compose exec api python manage.py dispatch_jobs --once
```

The dispatcher normally runs continuously. Its one-shot command is useful for a
controlled diagnosis. Additional dispatchers are safe on PostgreSQL, but adding
them does not increase OCR CPU capacity.

## Failure matrix

| Symptom | Interpretation | Safe next action |
| --- | --- | --- |
| Upload 400/413 | Bad metadata, signature/extension mismatch or size limit | Correct the payload; do not blindly retry |
| API 401/403 | Invalid/expired token or insufficient role | Refresh/re-authenticate; verify the expected user/role |
| Known document gives 404 for another user | Intended isolation | Do not broaden permissions to make the test pass |
| PATCH/DELETE 428 | Revision precondition missing | GET the document and use its quoted revision |
| PATCH/DELETE 412 | A newer metadata revision exists | Resolve conflicting changes against current data |
| Upload 409 with idempotency key | Key reused for different content/metadata | Use the original payload or a new logical request key |
| Pending job has no recent dispatch time | Dispatcher unavailable or DB query failure | Check dispatcher logs and database connectivity |
| Pending job has dispatch times but no attempts | Broker/worker unavailable or backlog | Check Redis, worker and queue age; do not mark documents succeeded manually |
| Processing longer than 240 seconds | Worker may have died; recovery also requires dispatcher | Inspect lease, worker exits, memory pressure and dispatcher |
| `invalid_document` | Corrupt/encrypted/undecodable input | Inspect a safe copy; upload a corrected file |
| `ocr_engine_unavailable` | Missing executable/language or engine invocation failure | Verify installed languages and image build; then reprocess the failed document |
| `ocr_timeout` | Per-page or whole-job budget exceeded | Reduce document size or tune capacity/limits after measuring; a retry may still fail |
| `storage_unavailable` | Missing/unreachable object or credential/configuration issue | Check storage health and policies without logging secrets |
| `integrity_error` | Stored byte count/hash differs | Investigate object corruption; do not silently accept the modified bytes |
| Failed `delete_object` job | Automatic cleanup attempts exhausted | Restore storage access, then explicitly rearm that job |
| Redis down causes 503 on reads/uploads | Throttling fails closed | Restore Redis; outbox still preserves previously committed jobs |

OCR errors are finite safe classifications. Exception types and stack locations
are logged without raw exception payloads; use a controlled local reproduction
for deeper debugging with non-sensitive sample files.

## Retry and recovery

Transient OCR failures have three total attempts, including the first. Invalid
documents do not retry automatically. `POST /api/v1/documents/{id}/reprocess/`
creates a new cycle only when the document is failed, checks ownership and
requires `If-Match`. It resets attempts and increments the metadata revision.

For a failed cleanup job, use its exact ID:

```bash
docker compose exec api python manage.py retry_cleanup <job-uuid>
```

This command only rearms one failed object-deletion job. It does not reprocess
OCR, modify unrelated rows or purge the database. Failed jobs and audit events
are otherwise retained for investigation.

## Controlled resilience demonstration

Use only a disposable evaluation instance. Upload a document, stop the worker,
confirm the API shows pending work, then start the worker again. The dispatcher
will republish the intent and processing can continue. Stopping Redis also affects
the throttle cache, so authenticated operations may return 503 until recovery.

```bash
docker compose stop worker
docker compose start worker
```

Do not terminate a production worker just to demonstrate recovery. Worker-kill,
lease-expiry and stale-result semantics have fault-injection tests; the PostgreSQL
suite additionally checks simultaneous claims.

## Backups and retention

PostgreSQL state, original objects and encryption/configuration secrets form one
recoverable system. Backing up the database alone is insufficient. Define RPO/RTO,
take encrypted database backups and object-store backups/versioning appropriate
to the data, and test a restore into an isolated environment. Pause processing
or reconcile restored job/object state before exposing a restored service.

The Compose named volumes are persistence, not backups. Object deletion may leave
versions/backups depending on provider policy. Legal hold and complete erasure
are not implemented. Decide audit/job retention before pruning history; this
repository deliberately has no automatic destructive retention job.

Expired refresh-token records can be removed with Django's provided command:

```bash
docker compose exec api python manage.py flushexpiredtokens
```

Schedule it in your deployment's normal maintenance system once that system is
defined. Do not use a development database account for a production test run.

## Health and monitoring

`/health/live/` answers whether the API process responds. `/health/ready/` is
administrator-only and checks DB/cache/storage connectivity. Neither guarantees
that OCR workers are making progress. Monitor at least:

- oldest pending job age, expired leases and failed cleanup jobs;
- OCR success/failure counts and durations by file type/page count;
- database query latency, connections, GIN size and vacuum pressure;
- Redis memory/backlog, S3 errors and worker memory/process exits;
- API latency, request-size rejections, authorization failures and rate limits.

Metrics dashboards, tracing exporters and alert routing are not bundled. JSON
logs and job records are the integration points; add observability infrastructure
according to the actual deployment, retention and privacy policy.

## Production checklist

- [ ] Use supported infrastructure; review current dependency/image advisories.
- [ ] Scan application and MinIO images; pin verified base-image digests for releases.
- [ ] Terminate HTTPS at a trusted ingress, set real hosts and configure HTTPS/HSTS.
- [ ] Only trust forwarding headers after the ingress strips spoofed client headers.
- [ ] Set upload-body/time limits at ingress as well as in Django.
- [ ] Provision separate restricted runtime and migration database roles.
- [ ] Use a secrets manager and independent JWT signing material; rotate credentials.
- [ ] Use supported private object storage with least-privilege credentials and TLS.
- [ ] Add malware quarantine, worker isolation/egress rules and per-user quotas.
- [ ] Separate broker/cache failure domains if availability objectives require it.
- [ ] Define audit retention, access controls, backup policy and restore drills.
- [ ] Add queue-age/lease/error monitoring; validate graceful rollout behavior.
- [ ] Load-test representative page sizes/languages and concurrent users.
- [ ] Run all PostgreSQL and full-stack tests; review skipped/failed tests explicitly.
- [ ] Review third-party terms and security/compliance needs before deployment.

Do not label this checklist complete solely because the unit suite or Compose
startup passed.
