"""Database-owned retries and fenced leases; Celery is the execution transport."""

import hashlib
import logging
import random
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from billiard.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.observability import request_id_context
from documents.models import Document, Job
from documents.ocr import MESSAGES, OCRFailure, extract
from documents.services import audit

logger = logging.getLogger("dms.jobs")


def backoff(attempt):
    return min(600, 5 * 2 ** max(0, attempt - 1)) + random.uniform(0, 2)


def _transition(document, state, job, error_code="", result=None):
    previous = document.status
    document.status = state
    document.attempts = job.attempts
    document.error_code = error_code
    document.error_message = MESSAGES.get(error_code, "")
    if result is not None:
        document.extracted_text = result.text
        document.processing_info = result.info
        document.processed_at = timezone.now()
    document.save()
    audit(
        document,
        "status_changed",
        job.request_id,
        previous=previous,
        status=state,
        attempt=job.attempts,
        error_code=error_code,
        job_id=str(job.id),
    )


def claim(job_id):
    with transaction.atomic():
        job = Job.objects.select_for_update().filter(pk=job_id).first()
        now = timezone.now()
        if not job or job.state != Job.State.PENDING or job.available_at > now:
            return None
        job.state = Job.State.RUNNING
        job.attempts += 1
        job.run_token = uuid.uuid4()
        job.lease_until = now + timedelta(seconds=settings.JOB_LEASE_SECONDS)
        job.save()
        if job.kind == Job.Kind.OCR:
            document = Document.objects.select_for_update().filter(pk=job.document_id).first()
            if not document:
                job.state = Job.State.SUCCEEDED
                job.lease_until = None
                job.save()
                return None
            _transition(document, Document.Status.PROCESSING, job)
        return job


def finish(job, result=None, failure=None):
    with transaction.atomic():
        current = Job.objects.select_for_update().get(pk=job.pk)
        if current.run_token != job.run_token or current.state != Job.State.RUNNING:
            return "stale"
        current.lease_until = None
        current.dispatched_at = None
        if failure:
            retry = failure.retryable and current.attempts < current.max_attempts
            current.state = Job.State.PENDING if retry else Job.State.FAILED
            current.error_code = failure.code
            current.available_at = timezone.now() + timedelta(seconds=backoff(current.attempts))
        else:
            current.state = Job.State.SUCCEEDED
            current.error_code = ""
        current.save()
        if current.kind == Job.Kind.OCR:
            document = Document.objects.select_for_update().filter(pk=current.document_id).first()
            if document:
                state = {
                    Job.State.PENDING: Document.Status.PENDING,
                    Job.State.FAILED: Document.Status.FAILED,
                    Job.State.SUCCEEDED: Document.Status.SUCCEEDED,
                }[current.state]
                _transition(document, state, current, current.error_code, result)
        logger.info(
            "job_finished",
            extra={
                "job_id": str(current.id),
                "document_id": str(current.document_id),
                "status": current.state,
                "error_code": current.error_code,
                "attempt": current.attempts,
            },
        )
        return current.state


def run_job(job_id):
    job = claim(job_id)
    if job is None:
        return "skipped"
    context_token = request_id_context.set(str(job.request_id))
    try:
        logger.info(
            "job_started",
            extra={
                "job_id": str(job.id),
                "document_id": str(job.document_id),
                "attempt": job.attempts,
            },
        )
        result = None
        if job.kind == Job.Kind.DELETE:
            # delete() is idempotent for missing keys in supported backends.
            try:
                default_storage.delete(job.storage_key)
            except Exception as exc:
                raise OCRFailure("storage_unavailable", retryable=True) from exc
        else:
            document = Document.objects.filter(pk=job.document_id).first()
            if document is None:
                return finish(job)
            with tempfile.TemporaryDirectory(prefix="dms-ocr-") as directory:
                path = Path(directory) / "original"
                digest = hashlib.sha256()
                size = 0
                try:
                    with (
                        default_storage.open(document.storage_key, "rb") as source,
                        path.open("wb") as target,
                    ):
                        while chunk := source.read(64 * 1024):
                            size += len(chunk)
                            if size > settings.MAX_UPLOAD_BYTES:
                                raise OCRFailure("integrity_error")
                            digest.update(chunk)
                            target.write(chunk)
                except OCRFailure:
                    raise
                except Exception as exc:
                    raise OCRFailure("storage_unavailable", retryable=True) from exc
                if size != document.size or digest.hexdigest() != document.sha256:
                    raise OCRFailure("integrity_error")
                result = extract(str(path), document.mime_type, directory)
        return finish(job, result=result)
    except OCRFailure as failure:
        logger.warning(
            "job_processing_error", extra={"job_id": str(job.id), "error_code": failure.code}
        )
        return finish(job, failure=failure)
    except SoftTimeLimitExceeded:
        return finish(job, failure=OCRFailure("ocr_timeout", retryable=True))
    except Exception:
        logger.exception(
            "job_unexpected_error",
            extra={"job_id": str(job.id), "document_id": str(job.document_id)},
        )
        return finish(job, failure=OCRFailure("unexpected_error", retryable=True))
    finally:
        request_id_context.reset(context_token)


def recover_expired(limit=100):
    count = 0
    candidates = Job.objects.filter(
        state=Job.State.RUNNING, lease_until__lte=timezone.now()
    ).values_list("pk", flat=True)[:limit]
    for identifier in list(candidates):
        with transaction.atomic():
            job = (
                Job.objects.select_for_update(skip_locked=True)
                .filter(pk=identifier, state=Job.State.RUNNING, lease_until__lte=timezone.now())
                .first()
            )
            if job is None:
                continue
            job.run_token = uuid.uuid4()  # Fence an old worker even if it resumes.
            # finish() acquires the same row lock within this transaction.
            job.save(update_fields=["run_token", "updated_at"])
            finish(job, failure=OCRFailure("worker_lost", retryable=True))
            count += 1
    return count


def dispatch_once(limit=100):
    from documents.tasks import execute_job

    recover_expired(limit)
    now = timezone.now()
    cutoff = now - timedelta(seconds=settings.JOB_REDISPATCH_SECONDS)
    due = Q(dispatched_at__isnull=True) | Q(dispatched_at__lte=cutoff)
    with transaction.atomic():
        jobs = list(
            Job.objects.select_for_update(skip_locked=True)
            .filter(due, state=Job.State.PENDING, available_at__lte=now)
            .order_by("available_at", "id")[:limit]
        )
        Job.objects.filter(pk__in=[job.pk for job in jobs]).update(dispatched_at=now)
    published = 0
    for job in jobs:
        try:
            execute_job.apply_async(
                args=[str(job.id)], task_id=str(job.id), retry=False, expires=300
            )
            published += 1
        except Exception:
            # A timestamp, not a permanent 'published' flag: failed or lost
            # publications are re-delivered after the dispatch interval.
            logger.exception(
                "job_publish_failed",
                extra={
                    "job_id": str(job.id),
                    "request_id": str(job.request_id),
                    "error_code": "broker_unavailable",
                },
            )
            break
    return published
