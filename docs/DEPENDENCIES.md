# Dependency and supply-chain notes

## Selection rationale

| Dependency | Purpose and choice |
| --- | --- |
| Django 5.2 LTS / DRF | Mandatory framework; explicit service transactions and serializer validation |
| PostgreSQL / psycopg | Mandatory database; JSONB, row locking and indexed full-text search without a second search service |
| Celery / Redis | Mandatory background transport; persisted scheduling remains in PostgreSQL |
| django-storages / boto3 | Established storage boundary with compatible S3 providers |
| SimpleJWT | Short access tokens, refresh rotation and blacklist support |
| PDFium bindings | Native PDF text/rendering; binary wheels avoid a separate Poppler deployment |
| Pillow | Image verification, dimensions, orientation and OCR preparation |
| Tesseract | Local printed-text OCR with English/Persian language packs |
| Gunicorn | Multi-process threaded WSGI serving, bounded process recycling |
| drf-spectacular | OpenAPI schema, interactive documentation and contract validation |
| pytest / pytest-django / coverage | Behavioral, database and fault-injection verification |
| Ruff | One formatter/linter with deterministic project configuration |
| requests / reportlab | Development acceptance client and deterministic test documents; not runtime API dependencies |

Python dependencies are pinned and hash-locked. Docker service tags specify
releases; MinIO server source is pinned to an upstream commit. Base-image tags
and apt package repositories can change, so complete bit-for-bit image
reproducibility is not claimed. Build artifacts must be scanned before a real
production release. No vulnerability scan result is implied by version pinning.

## Upstream terms and notices

This repository does not relicense dependencies. Installed wheels and container
components carry their own notices. The MinIO server image copies the upstream
license and is built from unmodified source. Review upstream terms before
redistributing containers or offering a hosted service.

- [Django license](https://github.com/django/django/blob/main/LICENSE)
- [Django REST Framework license](https://github.com/encode/django-rest-framework/blob/master/LICENSE.md)
- [Celery license](https://github.com/celery/celery/blob/main/LICENSE)
- [Redis licensing](https://github.com/redis/redis#license)
- [MinIO license](https://github.com/minio/minio/blob/RELEASE.2025-10-15T17-29-55Z/LICENSE)
- [Tesseract license](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE)
- [pypdfium2 licensing and bundled third-party notices](https://pypdfium2.readthedocs.io/en/stable/readme.html#licensing)

MinIO is used for local compatibility testing. Its source-only security release
and upstream maintenance status are reasons to choose a supported object-storage
service for production, not reasons to weaken the provider-neutral application
interface.
