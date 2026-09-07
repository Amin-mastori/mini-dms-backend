# Verification record

## Local execution

Executed on Python 3.12.13 with the pinned application libraries:

- Ruff lint and format checks.
- Django system check and migration generation.
- OpenAPI generation, validation and documentation endpoint tests.
- Portable API/workflow suite, including real English Tesseract image extraction
  and real PDFium text/rendering paths.
- Latest recorded portable suite: **114 passed, 7 PostgreSQL-only tests skipped**;
  application statement coverage **93.74%**. PostgreSQL-only additions exercise
  simultaneous metadata edits and owner-scoped idempotent uploads. The total also
  includes 20 image-bundle tests; application coverage excludes the CLI helper.

The portable suite uses test-only SQLite, a temporary filesystem storage backend,
a memory broker and fault-injected failures. It does not certify PostgreSQL
locking/full-text behavior, Redis transport, MinIO policies, Docker startup or
Persian OCR accuracy. The local machine did not provide Docker/PostgreSQL/Redis
services, so those were not silently substituted in the production configuration.

## Automated environment checks

`.github/workflows/ci.yml` defines two independent jobs:

1. **Quality and PostgreSQL tests:** pinned Python dependencies, real PostgreSQL,
   actual search/index/trigger/concurrency tests, coverage threshold and OpenAPI
   drift check.
2. **Real Compose acceptance:** builds all images, provisions a private bucket,
   starts the complete stack, runs the PostgreSQL suite inside the hardened test
   image, and exercises actual HTTP upload/OCR/download flows with two isolated
   users and PNG/JPEG/native/scanned PDFs.

The acceptance job also exports and reloads the MinIO image before starting
services with `--no-build`. Only a successful main-branch acceptance run
publishes the image bundle. `tests/test_minio_image.py` covers manifest/path/tag
validation, checksum failures, image mismatches and a mocked export/load round
trip. Those unit tests alone do not prove that Docker can import or run an image;
the real acceptance job supplies that separate check.

The Compose test service writes Coverage and pytest cache data to its writable
`/tmp` mount. Application code remains read-only under `/app`; this also avoids
host-dependent permission failures when the suite runs through Docker Desktop.

The bundle checksum helper reads fixed-size chunks and avoids
`hashlib.file_digest`, which is unavailable before Python 3.11. Its streaming
behavior is covered by a file larger than one chunk. Python 3.8 compatibility is
an intentional source-level contract for the local helper; CI executes it on the
project's tested Python 3.12 runtime and does not claim a separate Python 3.8
runtime matrix for the application.

Observed [CI run 34115690081](https://github.com/Amin-mastori/mini-dms-backend/actions/runs/34115690081),
for commit `e13de740aaa4fa4508ec9f82bceb14ae77a81f11`, completed both jobs successfully:

| Check | Observed result |
| --- | --- |
| Quality suite on Python 3.12.14 / PostgreSQL 17.11 | **121 passed**, **94.25% statement coverage** |
| Ruff, Django and migration drift | Passed |
| OpenAPI validation and checked-in schema comparison | Passed |
| Docker image builds and service startup | Passed |
| Real PNG/JPEG/native-PDF/scanned-PDF extraction | Passed |
| Two-user isolation, upload idempotency, search, pagination and revision conflicts | Passed |
| Authorized downloads and deletion audit retention | Passed |

The first quality run also exposed a test-database teardown warning: thread-local
connections in concurrency tests were still open. Test cleanup now closes each
thread's connections explicitly, and pytest infrastructure warnings are treated
as errors. Consult the [latest Actions results](https://github.com/Amin-mastori/mini-dms-backend/actions)
for subsequent commits; the table above names the exact observed baseline.

## Not established by the current tests

- Production throughput, p95/p99 latency or a one-million-document benchmark.
- High availability, backup restoration or regional disaster recovery.
- Security audit, penetration testing or an absence of dependency vulnerabilities.
- Handwriting recognition, layout fidelity or Persian/English OCR accuracy rates.
- Legal-hold, complete physical erasure or tamper-proof audit compliance.

These are explicit release/deployment responsibilities, not implicit guarantees.
