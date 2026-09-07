<div align="center">

# Mini DMS

### Private documents. Searchable knowledge. Recoverable processing.

A headless document-management backend built for clear ownership,
asynchronous extraction, and explainable operational behavior.

[![CI](https://github.com/Amin-mastori/mini-dms-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/Amin-mastori/mini-dms-backend/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2_LTS-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Celery](https://img.shields.io/badge/Celery-5.6-37814A?logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

[Quick start](#quick-start) · [API guide](#api-guide) · [Architecture](ARCHITECTURE.md) · [Windows guide](docs/WINDOWS_SETUP.md)

</div>

---

## Contents

- [Why this implementation](#why-this-implementation)
- [Quick start](#quick-start)
- [Services and technology](#services-and-technology)
- [Configuration](#configuration)
- [API guide](#api-guide)
- [Testing and quality](#testing-and-quality)
- [Operations and troubleshooting](#operations-and-troubleshooting)
- [Project map](#project-map)
- [Production boundary](#production-boundary)

## Why this implementation

This is an API-only backend: no application frontend, public file server or
external OCR service is required. Interactive OpenAPI pages are documentation,
not a product UI.

| Capability | Implementation |
| --- | --- |
| Upload | PDF, JPG/JPEG and PNG; streaming byte limits, signature/extension matching and SHA-256 integrity |
| Extraction | Local Tesseract for printed Persian/English; PDFium text-layer reuse or per-page rendering |
| Ownership | Every document query is scoped; administrators can manage all documents |
| Metadata | Typed fields plus bounded extensible JSON; server-owned timestamps |
| Search | PostgreSQL full-text vector and GIN index; text, metadata keys/values and tags; pagination |
| Reliability | Transactional outbox, persisted backoff, worker leases and fencing tokens |
| Storage | Private S3-compatible bucket through Django's storage interface; no file bytes in PostgreSQL |
| Concurrency | Owner-scoped upload idempotency and revision-checked metadata updates/deletion |
| Audit | Creation, metadata updates, deletion and processing transitions, including actor and request ID |
| Diagnostics | Structured JSON logs, consistent errors, health endpoints and administrator job inspection |
| Delivery | Hash-locked Python dependencies, Compose services, tests, OpenAPI and engineering documentation |

The implementation preserves all mandatory requirement areas. Scope decisions
are recorded in [ASSUMPTIONS.md](docs/ASSUMPTIONS.md); the requirement-to-code map
is in [REQUIREMENTS.md](docs/REQUIREMENTS.md).

## Quick start

### Prerequisites

- Docker Desktop or Docker Engine with Docker Compose v2.20+.
- Git and Python 3.8+ locally for the environment/image helper scripts. The
  application images use the tested Python 3.12 runtime.
- Internet access for the first image/dependency build.
- Recommended for evaluation: 4 CPU cores, 6 GiB available Docker memory and
  several GiB of free disk. This is a starting allocation, not a measured SLA.

Windows users can run these commands in the VS Code PowerShell terminal.
Linux/WSL users may need `python3` instead of `python`.

```bash
git clone https://github.com/Amin-mastori/mini-dms-backend.git
cd mini-dms-backend
python scripts/init_env.py
docker compose up --build -d --wait --wait-timeout 180
docker compose exec api python manage.py createsuperuser
```

Enter your own administrator username and a strong password when prompted.
There is no default account or public signup endpoint. Repository visibility
does not change the API's authentication or document-ownership controls.

`init_env.py` creates unique local secrets, does not print them and never
overwrites an existing `.env`. Keep `.env` private. Never paste it into an issue.

> [!NOTE]
> The first build can take several minutes. MinIO's October 2025 security
> release is source-only, so its image is built from a specific upstream commit.
> This avoids depending on the older official prebuilt image. Subsequent builds
> reuse Docker's cache. The final server image is a minimal non-root image with
> a compiled health probe and does not run `apt-get`. See
> [the storage decision](ARCHITECTURE.md#storage).

> [!TIP]
> If MinIO dependency downloads fail on your network, use the
> [verified CI-built MinIO image](docs/WINDOWS_SETUP.md#use-the-verified-ci-built-minio-image).
> The acceptance job exports and reloads the image, exercises the full stack,
> then publishes a seven-day download with a checksum and source revision.
> This avoids building MinIO locally; other services still need their usual
> images/dependencies. Keep your existing `.env` and Docker volumes.

After startup:

| Resource | Address |
| --- | --- |
| Interactive API docs | [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/) |
| ReDoc | [http://localhost:8000/api/redoc/](http://localhost:8000/api/redoc/) |
| OpenAPI schema | [http://localhost:8000/api/schema/](http://localhost:8000/api/schema/) |
| Liveness | [http://localhost:8000/health/live/](http://localhost:8000/health/live/) |
| Development storage console | [http://localhost:9001](http://localhost:9001) |

The document-create operation is documented only as `multipart/form-data`, so
Swagger renders its `file` property as a file picker rather than a JSON string.

Ports bind to `127.0.0.1`. PostgreSQL, Redis and the MinIO S3 API have no host
ports. Storage-console credentials are the `MINIO_ROOT_*` values in your local
`.env`; the application uses a different, bucket-scoped identity. Files are
downloaded through the authorized API, not a public MinIO URL.

### Migrations, updates and shutdown

The one-shot `migrate` service runs before API and worker startup. You can also
run migrations explicitly:

```bash
docker compose exec api python manage.py migrate --noinput
docker compose ps -a
docker compose logs --tail=100 api worker dispatcher
docker compose down
```

`down` stops services and preserves named volumes. **Do not add `-v` unless you
intend to erase the development database, broker data and stored documents.**
After pulling changes, repeat `docker compose up --build -d --wait`.

## Services and technology

| Service/component | Role | Reason |
| --- | --- | --- |
| `api` / Django + DRF + Gunicorn | Authenticated HTTP API | Mature validation, authentication, ORM and transactions |
| `db` / PostgreSQL | Documents, audit, jobs and search | One transactional source of truth; native JSONB and full-text indexing |
| `redis` | Celery broker and throttle cache | Mandatory stack; low-latency transport, not authoritative job state |
| `worker` / Celery | Bounded file decoding and OCR | CPU-heavy work is separated from web processes |
| `dispatcher` | Publish due jobs and recover expired leases | Survives broker outages and missed publications |
| `minio` | Development object storage | Exercises the same S3 integration used by managed storage |
| `storage-init` | Private bucket and scoped identity | Explicit initialization; root storage credentials are not passed to the API |
| `migrate` | One-shot schema migration | Avoids each web worker racing to migrate |
| `test` profile | PostgreSQL tests and smoke client | Reproducible evaluation without installing the full stack on the host |
| SimpleJWT | Short-lived access and rotating refresh tokens | Headless authentication with revocable refresh credentials |
| django-storages + boto3 | Storage adapter | Business code does not depend on MinIO APIs |
| PDFium + Tesseract | Text extraction | No document content sent to an external OCR provider |
| drf-spectacular | OpenAPI 3 | Executable API documentation and checked-in contract |
| pytest + Ruff | Behavioral and static quality | Fault injection, concurrency tests, formatting and linting |

Exact Python versions and hashes are in `requirements.txt` and
`requirements-dev.txt`. Dependency purposes, tradeoffs and references are
documented in [ARCHITECTURE.md](ARCHITECTURE.md).

## Configuration

The complete template is [.env.example](.env.example). Compose reads `.env` for
interpolation and passes only explicitly listed variables to each service.
Do not use `docker compose config` without `--quiet` in shared logs: expanded
configuration contains credentials.

| Variables | Meaning/default |
| --- | --- |
| `DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY` | Independent random secrets; generated locally |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,api`; set actual production hostnames |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | Database connection |
| `REDIS_PASSWORD`, `REDIS_URL`, `REDIS_CACHE_URL` | Broker DB 0 and throttle DB 1; URL password must match Redis |
| `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ADDRESSING_STYLE` | Provider connection; `http://minio:9000`, `us-east-1`, `path` in development |
| `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Private application bucket and identity |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Development bootstrap/console only, not application credentials |
| `OCR_LANGUAGES` | `eng+fas`; corresponding Tesseract language packs must be installed |
| `MAX_UPLOAD_BYTES` | `26214400` (25 MiB) |
| `MAX_OCR_PAGES`, `MAX_OCR_PIXELS`, `MAX_OCR_CHARS` | `20`, `20000000`, `200000` |
| `OCR_PAGE_TIMEOUT` | 45 seconds; whole task has separate 170/180-second soft/hard limits |
| `API_PORT`, `MINIO_CONSOLE_PORT` | Host ports `8000` / `9001` |
| `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_HSTS_SECONDS`, `TRUST_PROXY_HEADERS` | TLS/proxy controls; development defaults are not production TLS configuration |
| `LOG_LEVEL` | Framework root logging, default `INFO`; application audit-style operational events remain INFO |

Custom S3 providers require deployment-specific bucket/IAM provisioning; do not
run the MinIO initializer against another provider. For AWS S3, use an empty
endpoint URL and virtual addressing. Review [storage and production](ARCHITECTURE.md#storage)
before adapting Compose to managed services.

## API guide

All document, account and audit resources require a bearer token. Liveness and
API documentation are intentionally public. Readiness and job inspection require
an administrator. Use trailing slashes exactly as documented.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/v1/auth/token/` | Obtain access and refresh tokens |
| POST | `/api/v1/auth/token/refresh/` | Rotate a refresh token |
| POST | `/api/v1/auth/logout/` | Blacklist a refresh token; requires access token |
| GET | `/api/v1/auth/me/` | Current identity and role |
| GET, POST | `/api/v1/admin/users/` | Administrator account listing/provisioning |
| GET, POST | `/api/v1/documents/` | Paginated listing/search or multipart upload |
| GET, PATCH, DELETE | `/api/v1/documents/{id}/` | Retrieve, update metadata or delete |
| GET | `/api/v1/documents/{id}/download/` | Authorized attachment download |
| GET | `/api/v1/documents/{id}/status/` | Processing progress, attempts and safe error |
| GET | `/api/v1/documents/{id}/text/` | Extracted plain text and current status |
| POST | `/api/v1/documents/{id}/reprocess/` | Start a new attempt cycle for a failed document |
| GET | `/api/v1/audit-events/` | Owner-scoped history, including deleted documents |
| GET | `/api/v1/admin/jobs/` | Administrative job diagnostics |
| GET | `/health/live/`, `/health/ready/` | Process and dependency checks |

### 1. Authenticate

Examples below use Bash. In Windows PowerShell use `curl.exe` or the interactive
API documentation to avoid shell quoting differences. Values in angle brackets
are placeholders, not preconfigured credentials.

```bash
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<your-password>"}'
```

```json
{"refresh":"<refresh-token>","access":"<access-token>"}
```

Set the returned access token in your terminal or Swagger's **Authorize** dialog.
Do not paste tokens into screenshots, source files or shared logs.

```bash
export ACCESS_TOKEN='<access-token>'
```

Access tokens last 15 minutes. Refresh tokens last one day and rotate on use;
the previous refresh token is blacklisted. Logout does not immediately revoke an
already issued access token: it expires normally. Disabled accounts cannot use
their access tokens because authentication checks the current database user.

### 2. Provision a normal user

```bash
curl -X POST http://localhost:8000/api/v1/admin/users/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"reviewer","password":"<strong-password>","role":"user"}'
```

The response is `201` with `id`, `username`, `email`, `role`, `is_active` and
`date_joined`; the password is never returned. Only an administrator may set
`role` to `admin`.

### 3. Upload a document

```bash
curl -X POST http://localhost:8000/api/v1/documents/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Idempotency-Key: invoice-2026-001' \
  -F 'file=@invoice.pdf' \
  -F 'title=September invoice' \
  -F 'description=Supplier invoice for review' \
  -F 'document_type=invoice' \
  -F 'tags=["finance","2026"]' \
  -F 'metadata={"supplier":"Acme","invoice_number":"INV-001"}'
```

`201 Created` includes `Location`, `ETag: "1"`, `X-Request-ID` and a document
object. Example excerpt (the actual response includes all documented fields):

```json
{
  "id": "cc8e58da-c803-4fe1-8aad-79277412593b",
  "title": "September invoice",
  "filename": "invoice.pdf",
  "mime_type": "application/pdf",
  "size": 24819,
  "status": "pending",
  "revision": 1,
  "tags": ["finance", "2026"],
  "metadata": {"supplier": "Acme", "invoice_number": "INV-001"}
}
```

Upload acceptance is not an OCR success guarantee. Valid signatures can still
belong to damaged/encrypted files; full decoding happens in the isolated worker.
Storage keys and bucket addresses are not exposed in document responses.

Repeated requests with the same owner, idempotency key and normalized payload
return `200` and `Idempotent-Replayed: true`. A changed payload returns `409`.
Keys are optional; without one, identical uploads create separate documents.

### 4. Poll processing and retrieve text

```bash
export DOCUMENT_ID='<returned-document-id>'
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  "http://localhost:8000/api/v1/documents/$DOCUMENT_ID/status/"
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  "http://localhost:8000/api/v1/documents/$DOCUMENT_ID/text/"
```

```json
{"id":"cc8e58da-c803-4fe1-8aad-79277412593b","status":"succeeded","text":"Invoice INV-001 ..."}
```

States are `pending`, `processing`, `succeeded`, `failed`. A retry returns the
document to `pending` with its safe error code and attempts visible. Poll at a
reasonable interval, such as every 2-5 seconds. A blank document may succeed
with empty text and a warning. No confidence score or OCR accuracy is fabricated.

### 5. Search and paginate

```bash
curl -G http://localhost:8000/api/v1/documents/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode 'q=Acme invoice' \
  --data-urlencode 'status=succeeded' \
  --data-urlencode 'page_size=20'
```

```json
{"count":1,"next":null,"previous":null,"results":[{"id":"cc8e58da-c803-4fe1-8aad-79277412593b","title":"September invoice"}]}
```

The excerpt abbreviates list fields. Page size is capped at 100. `q` supports
PostgreSQL web-search tokens, quoted phrases and `OR`; ordinary space-separated
terms use AND. Search is not substring/fuzzy matching. Optional filters:
`status`, exact `document_type`, exact case-sensitive `tag`, `page`, `page_size`.
Persian/Arabic variants of kaf/yeh and zero-width non-joiners are normalized, but
there is no Persian stemming. No query can bypass ownership filtering.

### 6. Update metadata safely

```bash
curl -X PATCH "http://localhost:8000/api/v1/documents/$DOCUMENT_ID/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' -H 'If-Match: "1"' \
  -d '{"title":"Approved invoice","metadata":{"supplier":"Acme","approved":true}}'
```

The response includes `revision: 2` and `ETag: "2"`. Missing `If-Match` returns
`428`; a stale revision returns `412`. Retrieve the latest document and resolve
the conflict before resubmitting. Unspecified fields remain unchanged. Supplied
`metadata` and `tags` replace their complete previous values; they do not deep
merge. Unknown and read-only fields are rejected.

OCR status updates do not change the metadata revision. Original file bytes
cannot be replaced through PATCH.

### 7. Download, reprocess, delete and audit

```bash
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  "http://localhost:8000/api/v1/documents/$DOCUMENT_ID/download/" -o downloaded.pdf

# Only for a FAILED document; use its current revision.
curl -X POST "http://localhost:8000/api/v1/documents/$DOCUMENT_ID/reprocess/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'If-Match: "2"'

# Use the latest revision; a reprocess request also increments it.
curl -X DELETE "http://localhost:8000/api/v1/documents/$DOCUMENT_ID/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'If-Match: "3"'

curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  "http://localhost:8000/api/v1/audit-events/?document_id=$DOCUMENT_ID"
```

Delete returns `204`: the document immediately disappears from the API, while
object deletion is retried asynchronously. History remains accessible to the
owner and administrators. Download streams use `attachment` and `nosniff`;
the API authorizes access before opening private storage.

### Error contract

```json
{
  "error": {
    "code": "revision_conflict",
    "message": "The document was modified. Retrieve it again before retrying.",
    "details": {},
    "request_id": "224eb4c6-e9f9-42d0-83e0-d4257e6b03c6"
  }
}
```

Validation errors include field details. Errors never deliberately include
tracebacks, credentials or OCR content. Capture `X-Request-ID` for support.
Health endpoints have their own compact status/checks response.

| Status | Meaning |
| --- | --- |
| 400 / 413 / 415 | Invalid input / oversized request / unsupported request encoding |
| 401 / 403 | Missing or invalid authentication / insufficient role |
| 404 | Resource absent or outside your ownership scope |
| 409 | Idempotency or processing-state conflict |
| 412 / 428 | Stale / missing revision precondition |
| 429 | Throttled; respect `Retry-After` |
| 500 / 503 | Unexpected fault / unavailable dependency |

## Testing and quality

### Canonical PostgreSQL suite

```bash
docker compose --profile test run --build --rm test pytest --cov --cov-fail-under=90
docker compose --profile test run --rm test ruff check .
docker compose --profile test run --rm test ruff format --check .
```

Tests use a separate `test_dms` database; do not point test settings at production.
The database account needs permission to create a test database in this
development deployment. Storage and transport are controlled doubles in the
contract suite, even when the database is real. PostgreSQL-specific tests check
GIN/trigger presence, search semantics and concurrent job claims.

### Real-stack acceptance test

After creating your administrator and starting the complete stack:

```bash
docker compose --profile test run --build --rm test python scripts/smoke_test.py --username admin
```

Enter your administrator password at the prompt. This goes through actual HTTP,
private MinIO storage, Redis transport, Celery execution and PostgreSQL. It checks
PNG, JPEG, native/scanned PDFs, two-user isolation, idempotency, revision
conflicts, search, pagination, downloads and deletion audit.

Run against a disposable/evaluation instance. It creates two test accounts and
deletes its uploaded documents. Accounts and audit history intentionally remain;
it does not erase unrelated data. Physical object deletion is asynchronous.

### Fast local development

```bash
python -m venv .venv
# Linux / WSL:
source .venv/bin/activate
# PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements-dev.txt
pytest --cov --cov-fail-under=90
ruff check .
```

The fast suite uses **test-only SQLite**, local temporary storage and a memory
transport. It is not the deployment backend and does not prove PostgreSQL,
Redis or S3 behavior. PostgreSQL tests skip here. Real Tesseract tests also skip
if the executable is missing; Docker includes it. Do not present skipped tests
as passed. [VERIFICATION.md](docs/VERIFICATION.md) records the verification boundary.

### API contract and CI

The workflow runs static checks, the PostgreSQL suite and a separate full Compose
acceptance job. Read the actual [Actions results](https://github.com/Amin-mastori/mini-dms-backend/actions)
for evidence; a badge is not a substitute for the underlying logs.

```bash
docker compose exec api python manage.py spectacular --validate --fail-on-warn
```

The checked-in [OpenAPI schema](docs/openapi.yaml) can be imported into Postman
or another OpenAPI client. When changing dependencies, update `pyproject.toml`,
recompile both hash-locked requirements with `uv pip compile --generate-hashes`
(add `--extra dev` for the development lock), then rerun both CI jobs.

## Operations and troubleshooting

Start with [OPERATIONS.md](docs/OPERATIONS.md), which includes request-ID tracing,
worker recovery, storage failures, backup/restore considerations and production
checks. Useful commands:

```bash
docker compose ps -a
docker compose logs -f api worker dispatcher
docker compose exec api python manage.py dispatch_jobs --once
docker compose exec worker tesseract --list-langs
docker compose exec api python manage.py flushexpiredtokens
```

The continuously running dispatcher already publishes jobs. `--once` is a
diagnostic/manual alternative, not a second required scheduler. There is no
Celery Beat dependency and no Redis result backend.

## Project map

| Path | Responsibility |
| --- | --- |
| `accounts/` | JWT endpoints, identity and administrator provisioning |
| `documents/models.py` | Document, durable job and audit records |
| `documents/services.py` | Transactional upload/update/delete/reprocess use cases |
| `documents/jobs.py` | Claim, fence, retry, recover and dispatch jobs |
| `documents/ocr.py` | Bounded PDF/image decoding and local extraction |
| `documents/views.py` | Owner-scoped API and PostgreSQL search |
| `documents/migrations/` | Schema and search-vector trigger |
| `core/` | Errors, correlation logging, upload bounds, pagination and health |
| `config/` | Django/Celery configuration and routes |
| `tests/` | Behavior, fault-injection, actual OCR and PostgreSQL concurrency tests |
| `scripts/` | Safe environment generation, bucket initialization and acceptance client |
| `docker/minio.Dockerfile` | Upstream-commit-pinned development MinIO build |
| `compose.yaml`, `Dockerfile` | Service topology and non-root application image |
| `docs/` | API contract, evaluation, assumptions and operations |
| `ARCHITECTURE.md` | Decisions, tradeoffs, failure behavior and growth plan |

## Production boundary

This is an evaluation-ready design with production-oriented controls, **not a
claim of a completed production rollout or security certification**. Compose is
single-host: no HA, TLS termination, malware scanner, centralized monitoring,
per-user storage quota, legal hold, SSO or backup automation is supplied.

The development PostgreSQL role has bootstrap/test privileges; production needs
separate migration and restricted runtime roles. MinIO is a development adapter,
not a recommendation to run an unmaintained storage deployment in production.
Use a supported private object store, review current advisories, scan built images
and complete the [production checklist](docs/OPERATIONS.md#production-checklist).

No repository-wide redistribution license has been selected. Public visibility
alone does not grant reuse rights. Third-party components retain their own
licenses; see [DEPENDENCIES.md](docs/DEPENDENCIES.md).
