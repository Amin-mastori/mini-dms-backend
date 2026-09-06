# Requirement traceability

| Requirement | Implementation | Verification |
| --- | --- | --- |
| 1. Document upload | `UploadSerializer`, `BoundedUploadHandler`, `create_document` | Signature, extension, empty/large input, hashing, async intent and private storage tests |
| 2. Async OCR and status | `documents/ocr.py`, `documents/jobs.py`, status/text actions | Native/scanned PDF paths, actual Tesseract, safe failures and state transitions |
| 3. Extensible metadata | Typed fields, bounded tags/JSON object, timestamps and strict PATCH | Unknown/read-only fields, depth/size/type validation and optimistic update tests |
| 4. Search and pagination | Search vector, PostgreSQL trigger, GIN, normalized query and paginated results | PostgreSQL token/Persian/index tests; metadata/tag/text search and isolation |
| 5. Document management | Create/list/retrieve/PATCH/DELETE/status/text/download APIs | CRUD, conflict, owner/admin and delete-history behavior |
| 6. External/object storage | Django S3 adapter, private MinIO, cleanup intents | Controlled storage fault tests; real-stack upload/download acceptance |
| 7. Celery/Redis processing | Durable outbox/dispatcher, Celery entrypoint, bounded attempts and leases | Duplicate delivery, broker failure, worker loss, stale-token fencing and task tests |
| 8. Authentication/authorization | JWT, active database user, staff/admin distinction and owner-scoped queries | Login/refresh/logout, invalid/disabled users, admin provisioning and two-user isolation |
| 9. Audit log | Transactional `AuditEvent`; history survives document deletion | Create, metadata, deletion, processing transitions and correlation tests |
| 10. Error handling | Stable error envelope, safe classifications and JSON logs | Validation/auth/conflict/storage/Redis/500 handling and secret-redaction tests |
| 11. Testing | Contract, PostgreSQL, OCR and HTTP acceptance layers | pytest suite, coverage gate and Compose smoke test |
| 12. Docker | App stages plus PostgreSQL, Redis, MinIO, worker, dispatcher and one-shot setup | CI Compose config/build/start and full-stack acceptance job |
| 13. Documentation | README, Windows setup, operations, checked-in OpenAPI and interactive docs | Schema validation/drift check; docs route tests |
| 14. Architecture | Root `ARCHITECTURE.md` | Decisions, failure models, bottlenecks, limitations and million-document growth reasoning |

No mandatory requirement was dropped to implement an optional feature. A
particular verification is only considered completed when its actual execution
result is recorded; test source alone is not evidence that a service ran.
