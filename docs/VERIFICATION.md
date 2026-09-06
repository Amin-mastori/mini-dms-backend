# Verification record

## Local execution

Executed on Python 3.12.13 with the pinned application libraries:

- Ruff lint and format checks.
- Django system check and migration generation.
- OpenAPI generation, validation and documentation endpoint tests.
- Portable API/workflow suite, including real English Tesseract image extraction
  and real PDFium text/rendering paths.
- Latest recorded portable suite: **88 passed, 7 PostgreSQL-only tests skipped**;
  application statement coverage **93.74%**. PostgreSQL-only additions exercise
  simultaneous metadata edits and owner-scoped idempotent uploads.

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
   starts the complete stack and runs actual HTTP upload/OCR/download flows with
   two isolated users and PNG/JPEG/native/scanned PDFs.

Check the [actual CI run](https://github.com/Amin-mastori/mini-dms-backend/actions)
for the relevant commit. Defining a job does not mean it passed. This file will
be updated with observed CI results when available.

## Not established by the current tests

- Production throughput, p95/p99 latency or a one-million-document benchmark.
- High availability, backup restoration or regional disaster recovery.
- Security audit, penetration testing or an absence of dependency vulnerabilities.
- Handwriting recognition, layout fidelity or Persian/English OCR accuracy rates.
- Legal-hold, complete physical erasure or tamper-proof audit compliance.

These are explicit release/deployment responsibilities, not implicit guarantees.
