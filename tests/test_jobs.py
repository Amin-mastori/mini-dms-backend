import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.files.storage import default_storage
from django.utils import timezone

from documents.jobs import claim, dispatch_once, finish, recover_expired, run_job
from documents.models import AuditEvent, Document, Job
from documents.ocr import ExtractionResult, OCRFailure
from documents.tasks import execute_job

pytestmark = pytest.mark.django_db


def ocr_job(document):
    return Job.objects.get(document_id=document.id, kind=Job.Kind.OCR)


def test_workflow_success_stores_text_and_status_events(document):
    job = ocr_job(document)
    with patch(
        "documents.jobs.extract",
        return_value=ExtractionResult("supplier uniqueocrtext", {"pages": 1}),
    ):
        assert run_job(str(job.id)) == "succeeded"
    document.refresh_from_db()
    assert document.status == "succeeded"
    assert document.extracted_text == "supplier uniqueocrtext"
    assert "uniqueocrtext" in document.search_text
    assert document.attempts == 1 and document.processed_at
    assert document.revision == 1
    states = list(
        AuditEvent.objects.filter(action="status_changed")
        .order_by("created_at")
        .values_list("details", flat=True)
    )
    assert [event["status"] for event in states] == ["processing", "succeeded"]


def test_duplicate_delivery_and_missing_job_are_safe(document):
    job = ocr_job(document)
    with patch("documents.jobs.extract", return_value=ExtractionResult("text", {})) as extractor:
        assert run_job(str(job.id)) == "succeeded"
        assert run_job(str(job.id)) == "skipped"
        extractor.assert_called_once()
    assert run_job(str(uuid.uuid4())) == "skipped"


def test_permanent_failure_does_not_retry(document):
    job = ocr_job(document)
    with patch("documents.jobs.extract", side_effect=OCRFailure("invalid_document")):
        assert run_job(job.id) == "failed"
    document.refresh_from_db()
    job.refresh_from_db()
    assert document.status == "failed" and job.attempts == 1
    assert document.error_code == "invalid_document"


def test_transient_failure_retries_with_backoff_then_exhausts(document):
    job = ocr_job(document)
    for attempt in range(1, 4):
        Job.objects.filter(pk=job.pk).update(available_at=timezone.now())
        before = timezone.now()
        with patch("documents.jobs.extract", side_effect=OCRFailure("ocr_timeout", retryable=True)):
            state = run_job(job.id)
        job.refresh_from_db()
        assert job.attempts == attempt
        assert job.available_at > before
        assert state == ("failed" if attempt == 3 else "pending")
    document.refresh_from_db()
    assert document.status == "failed" and document.attempts == 3


def test_lease_recovery_fences_old_worker(document):
    job = ocr_job(document)
    old_claim = claim(job.id)
    assert claim(job.id) is None
    Job.objects.filter(pk=job.id).update(lease_until=timezone.now() - timedelta(seconds=1))
    assert recover_expired() == 1
    assert finish(old_claim, result=ExtractionResult("stale overwrite", {})) == "stale"
    document.refresh_from_db()
    assert document.status == "pending" and not document.extracted_text
    Job.objects.filter(pk=job.id).update(available_at=timezone.now())
    new_claim = claim(job.id)
    assert new_claim.run_token != old_claim.run_token
    assert finish(new_claim, result=ExtractionResult("fresh result", {})) == "succeeded"


def test_lost_worker_on_final_attempt_fails_document(document):
    job = ocr_job(document)
    Job.objects.filter(pk=job.id).update(attempts=2)
    claim(job.id)
    Job.objects.filter(pk=job.id).update(lease_until=timezone.now() - timedelta(seconds=1))
    recover_expired()
    document.refresh_from_db()
    assert document.status == "failed"
    assert document.error_code == "worker_lost"


def test_deleted_document_during_processing_is_not_resurrected(document):
    job = ocr_job(document)
    running = claim(job.id)
    document.delete()
    assert finish(running, result=ExtractionResult("discarded", {})) == "succeeded"
    assert not Document.objects.exists()


def test_deleted_document_before_delivery_is_noop(document):
    job = ocr_job(document)
    document.delete()
    assert run_job(job.id) == "skipped"
    job.refresh_from_db()
    assert job.state == "succeeded"


def test_object_cleanup_is_idempotent(client, document):
    key, identifier = document.storage_key, document.id
    client.delete(f"/api/v1/documents/{identifier}/", HTTP_IF_MATCH='"1"')
    job = Job.objects.get(kind=Job.Kind.DELETE, document_id=identifier, state=Job.State.PENDING)
    assert run_job(job.id) == "succeeded"
    assert not default_storage.exists(key)
    assert run_job(job.id) == "skipped"


def test_storage_failures_are_retryable(document):
    job = ocr_job(document)
    with patch("documents.jobs.default_storage.open", side_effect=OSError("private-bucket-secret")):
        assert run_job(job.id) == "pending"
    document.refresh_from_db()
    assert document.error_code == "storage_unavailable"
    assert "private-bucket-secret" not in document.error_message


def test_integrity_mismatch_is_permanent(document):
    document.sha256 = "0" * 64
    document.save()
    assert run_job(ocr_job(document).id) == "failed"
    document.refresh_from_db()
    assert document.error_code == "integrity_error"


def test_unexpected_error_and_soft_timeout_are_bounded(document):
    from billiard.exceptions import SoftTimeLimitExceeded

    job = ocr_job(document)
    for failure in (RuntimeError("secret"), SoftTimeLimitExceeded()):
        Job.objects.filter(pk=job.id).update(available_at=timezone.now())
        with patch("documents.jobs.extract", side_effect=failure):
            assert run_job(job.id) == "pending"


def test_dispatcher_republishes_after_broker_failure(document, settings):
    job = ocr_job(document)
    with patch(
        "documents.tasks.execute_job.apply_async", side_effect=ConnectionError("redis down")
    ):
        assert dispatch_once() == 0
    job.refresh_from_db()
    assert job.state == "pending"
    with patch("documents.tasks.execute_job.apply_async") as publisher:
        assert dispatch_once() == 0
        Job.objects.filter(pk=job.id).update(
            dispatched_at=timezone.now() - timedelta(seconds=settings.JOB_REDISPATCH_SECONDS + 1)
        )
        assert dispatch_once() == 1
        publisher.assert_called_once()


def test_celery_task_entrypoint_invokes_workflow(document):
    with patch("documents.jobs.extract", return_value=ExtractionResult("celery entrypoint", {})):
        result = execute_job.apply(args=[str(ocr_job(document).id)], throw=True)
    assert result.result == "succeeded"
    document.refresh_from_db()
    assert document.extracted_text == "celery entrypoint"


def test_manual_reprocessing_is_scoped_and_limited_to_failed(client, document):
    url = f"/api/v1/documents/{document.id}/reprocess/"
    assert client.post(url, HTTP_IF_MATCH='"1"').status_code == 409
    job = ocr_job(document)
    with patch("documents.jobs.extract", side_effect=OCRFailure("invalid_document")):
        run_job(job.id)
    response = client.post(url, HTTP_IF_MATCH='"1"')
    assert response.status_code == 202
    assert response.data["status"] == "pending" and response.data["revision"] == 2
    assert Job.objects.filter(document_id=document.id, kind="ocr").count() == 2


def test_cleanup_failure_retries():
    job = Job.objects.create(kind=Job.Kind.DELETE, storage_key="missing-key", max_attempts=8)
    with patch("documents.jobs.default_storage.delete", side_effect=OSError("offline")):
        assert run_job(job.id) == "pending"


def test_abandoned_upload_intent_eventually_cleans_orphan():
    from django.core.files.base import ContentFile

    key = default_storage.save("orphan/file", ContentFile(b"orphan data"))
    job = Job.objects.create(kind=Job.Kind.DELETE, storage_key=key, available_at=timezone.now())
    assert run_job(job.id) == "succeeded"
    assert not default_storage.exists(key)
