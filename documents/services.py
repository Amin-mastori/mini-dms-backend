import hashlib
import json
import logging
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from core.errors import Conflict, PreconditionFailed, PreconditionRequired, ServiceUnavailable
from documents.models import AuditEvent, Document, Job

logger = logging.getLogger("dms.documents")


def audit(document, action, request_id, actor=None, **details):
    AuditEvent.objects.create(
        document_id=document.id,
        owner_id=document.owner_id,
        actor=actor,
        actor_kind="user" if actor else "system",
        action=action,
        request_id=request_id,
        details=details,
    )


def check_revision(document, header):
    if header is None:
        raise PreconditionRequired()
    if header != f'"{document.revision}"':
        raise PreconditionFailed()


def scoped_documents(user):
    queryset = Document.objects.all()
    return queryset if user.is_staff else queryset.filter(owner=user)


def _replay(user, key, fingerprint):
    existing = Document.objects.filter(owner=user, idempotency_key=key).first() if key else None
    if existing and existing.request_fingerprint != fingerprint:
        raise Conflict("This Idempotency-Key was already used with a different payload.")
    return existing


def create_document(user, data, key, request_id):
    data = dict(data)
    upload = data.pop("file")
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                **data,
                "sha256": upload.sha256,
                "filename": upload.name,
            },
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    existing = _replay(user, key, fingerprint)
    if existing:
        return existing, False
    document_id = uuid.uuid4()
    storage_key = f"documents/{user.pk}/{document_id}/{uuid.uuid4().hex}"
    # A committed cleanup intent closes the object-store/DB crash gap. It is
    # cancelled atomically when the document is committed. No network calls in
    # the document transaction, and no broker access in the API process.
    intent = Job.objects.create(
        kind=Job.Kind.DELETE,
        storage_key=storage_key,
        document_id=document_id,
        max_attempts=8,
        available_at=timezone.now() + timedelta(hours=1),
        request_id=request_id,
    )
    try:
        actual_key = default_storage.save(storage_key, upload)
        if actual_key != storage_key:
            intent.storage_key = actual_key
            intent.save(update_fields=["storage_key", "updated_at"])
        with transaction.atomic():
            # Serialize idempotency decisions per owner, not across users.
            get_user_model().objects.select_for_update().get(pk=user.pk)
            existing = _replay(user, key, fingerprint)
            if existing:
                intent.available_at = timezone.now()
                intent.save(update_fields=["available_at", "updated_at"])
                return existing, False
            document = Document.objects.create(
                id=document_id,
                owner=user,
                storage_key=actual_key,
                filename=upload.name,
                mime_type=upload.detected_type,
                size=upload.size,
                sha256=upload.sha256,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                **data,
            )
            audit(document, "created", request_id, user)
            Job.objects.create(kind=Job.Kind.OCR, document_id=document.id, request_id=request_id)
            intent.state = Job.State.SUCCEEDED
            intent.save(update_fields=["state", "updated_at"])
        return document, True
    except Conflict:
        Job.objects.filter(pk=intent.pk).update(available_at=timezone.now())
        raise
    except Exception as exc:
        # The precommitted intent still cleans up even if this update cannot run.
        try:
            Job.objects.filter(pk=intent.pk).update(available_at=timezone.now())
        except Exception:
            logger.exception("upload_cleanup_deferred", extra={"document_id": str(document_id)})
        logger.exception("upload_failed", extra={"document_id": str(document_id)})
        raise ServiceUnavailable() from exc


def update_document(document, data, user, request_id, revision):
    check_revision(document, revision)
    changed = [field for field, value in data.items() if getattr(document, field) != value]
    if changed:
        for field in changed:
            setattr(document, field, data[field])
        document.revision += 1
        document.save()
        audit(
            document,
            "metadata_updated",
            request_id,
            user,
            fields=sorted(changed),
            revision=document.revision,
        )
    return document


def delete_document(document, user, request_id, revision):
    check_revision(document, revision)
    audit(document, "deleted", request_id, user)
    Job.objects.create(
        kind=Job.Kind.DELETE,
        document_id=document.id,
        storage_key=document.storage_key,
        max_attempts=8,
        request_id=request_id,
    )
    document.delete()


def reprocess_document(document, user, request_id, revision):
    check_revision(document, revision)
    if document.status != Document.Status.FAILED:
        raise Conflict("Only failed documents can be reprocessed.")
    document.status = Document.Status.PENDING
    document.attempts = 0
    document.error_code = ""
    document.error_message = ""
    document.revision += 1
    document.save()
    audit(document, "reprocess_requested", request_id, user, status="pending")
    Job.objects.create(kind=Job.Kind.OCR, document_id=document.id, request_id=request_id)
    return document
