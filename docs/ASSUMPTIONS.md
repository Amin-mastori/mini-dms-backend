# Scope and assumptions

Recorded before implementation. The mandatory stack and all fourteen requirement
areas are retained. Extra features solve failure modes, not unrelated product scope.

| Ambiguity | Decision |
| --- | --- |
| Who owns a document? | One user. Regular users see only their own documents across every endpoint, including search, downloads, OCR and audit. Staff users are administrators. No sharing or organizations yet. |
| Account provisioning | No public registration. An initial administrator is created interactively; administrators provision ordinary users through the API. |
| OCR language | Printed English and Persian (`eng+fas`), configurable. No handwriting or accuracy guarantee. |
| PDF text layers | Reuse nonempty text layers per page; OCR scanned pages. Both run asynchronously. |
| File limits | 25 MiB, 20 pages, 20 million pixels per rendered page, 200,000 extracted characters. Configurable within operational capacity. |
| Metadata | Typed title, description, document type and tags, plus a bounded JSON object for extension. PATCH replaces supplied tags/metadata as a whole. |
| Updates | Original bytes are immutable. Metadata changes and deletion require the current metadata revision in `If-Match`. OCR progress does not invalidate this revision. |
| Upload retries | Optional owner-scoped `Idempotency-Key`; same key and payload returns the existing document. Different payload gives 409. No cross-user deduplication. Keys expire when the document is deleted. |
| Deletion | Immediate removal from API/database, asynchronous object deletion with bounded retries. Audit and job records survive. No trash, legal hold or object-version erasure guarantee. |
| Search | PostgreSQL token-based full-text search over normalized title, description, type, tags, JSON keys/values and extracted text. No fuzzy/substring or Persian stemming guarantee. |
| Retry ownership | PostgreSQL owns job state, leases and retry schedule. Celery transports execution; task results are not a second source of truth. |
| Production | Secure defaults and operational guidance, not a claim of completed security audit, load test, HA or compliance certification. Compose is a single-host development/evaluation deployment. |
| Tooling | VS Code is optional. Docker Compose is the canonical execution environment; no UI is part of the application. OpenAPI is the API contract. |

Meaningful extras: transactional outbox, abandoned-upload cleanup, worker leases
with fencing tokens, bounded persisted backoff, optimistic concurrency, structured
correlation logs, private streamed downloads, admin diagnostics, and real-stack
smoke tests. Folder management, document versions and enterprise ACLs are deferred.
