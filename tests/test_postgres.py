from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection

from documents.jobs import claim
from documents.models import Document, Job

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Real PostgreSQL required"),
]


def test_trigger_indexes_metadata_and_ocr(client, document):
    document.extracted_text = "unicornmarker"
    document.metadata = {"department": "treasurymarker"}
    document.tags = ["confidentialmarker"]
    document.save()
    for word in ("unicornmarker", "treasurymarker", "confidentialmarker", "quarterly"):
        response = client.get("/api/v1/documents/", {"q": word})
        assert response.data["count"] == 1
    assert client.get("/api/v1/documents/?tag=confidentialmarker").data["count"] == 1
    document.metadata = {}
    document.save()
    assert client.get("/api/v1/documents/?q=treasurymarker").data["count"] == 0


def test_persian_normalization(client, document):
    document.title = (
        "\u06af\u0632\u0627\u0631\u0634 \u0634\u0631\u0643\u062a \u06a9\u06cc\u0627\u0646"
    )
    document.save()
    assert (
        client.get(
            "/api/v1/documents/", {"q": "\u0634\u0631\u06a9\u062a \u0643\u064a\u0627\u0646"}
        ).data["count"]
        == 1
    )


def test_fulltext_is_token_not_substring(client, document):
    document.title = "alphabetic"
    document.save()
    assert client.get("/api/v1/documents/?q=alpha").data["count"] == 0
    assert client.get("/api/v1/documents/?q=alphabetic").data["count"] == 1


def test_search_gin_and_trigger_exist():
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'doc_search_gin'")
        assert "USING gin" in cursor.fetchone()[0]
        cursor.execute("SELECT tgname FROM pg_trigger WHERE tgname = 'document_search_refresh'")
        assert cursor.fetchone()


def test_two_workers_cannot_claim_same_job(document):
    job = Job.objects.get(document_id=document.id, kind="ocr")

    def worker():
        close_old_connections()
        try:
            return claim(job.id) is not None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(results) == [False, True]
    assert Document.objects.get(pk=document.id).attempts == 1


def test_two_concurrent_metadata_writes_only_one_wins(user, document):
    from rest_framework.test import APIClient

    def update(title):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user)
            return client.patch(
                f"/api/v1/documents/{document.id}/",
                {"title": title},
                format="json",
                HTTP_IF_MATCH='"1"',
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["First edit", "Second edit"]))
    assert sorted(results) == [200, 412]
    document.refresh_from_db()
    assert document.revision == 2


def test_concurrent_idempotent_upload_has_one_document(user, upload_file):
    from threading import Barrier
    from unittest.mock import patch

    from django.core.files.storage import default_storage
    from rest_framework.test import APIClient

    rendezvous = Barrier(2)
    original_save = default_storage.save

    def simultaneous_save(name, content):
        result = original_save(name, content)
        rendezvous.wait(timeout=10)
        return result

    def upload(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user)
            response = client.post(
                "/api/v1/documents/",
                {"title": "Concurrent", "file": upload_file()},
                format="multipart",
                HTTP_IDEMPOTENCY_KEY="concurrent-key",
            )
            return response.status_code, response.data.get("id")
        finally:
            close_old_connections()

    with (
        patch("documents.services.default_storage.save", side_effect=simultaneous_save),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(upload, range(2)))
    assert sorted(status for status, _ in results) == [200, 201]
    assert len({identifier for _, identifier in results}) == 1
    assert Document.objects.count() == 1
    assert Job.objects.filter(kind="ocr").count() == 1
    assert Job.objects.filter(kind="delete_object", state="pending").count() == 1
