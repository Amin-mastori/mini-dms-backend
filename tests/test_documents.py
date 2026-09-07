import json
from unittest.mock import patch

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

from documents.models import AuditEvent, Document, Job

pytestmark = pytest.mark.django_db


def test_upload_is_private_async_and_audited(client, upload_file, user):
    with patch("documents.tasks.execute_job.apply_async") as publish:
        response = client.post(
            "/api/v1/documents/",
            {
                "file": upload_file(),
                "title": "Invoice",
                "tags": '["finance"]',
                "metadata": '{"supplier":"Acme"}',
            },
            format="multipart",
        )
    assert response.status_code == 201
    document = Document.objects.get(pk=response.data["id"])
    assert document.owner == user
    assert document.status == "pending"
    assert default_storage.exists(document.storage_key)
    assert document.metadata == {"supplier": "Acme"}
    assert Job.objects.filter(kind="ocr", document_id=document.id, state="pending").count() == 1
    assert AuditEvent.objects.filter(document_id=document.id, action="created", actor=user).exists()
    assert "storage_key" not in response.data
    assert "extracted_text" not in response.data
    assert response["ETag"] == '"1"'
    publish.assert_not_called()


@pytest.mark.parametrize(
    ("encoded_tags", "expected_tags"),
    [
        ('["finance","urgent"]', ["finance", "urgent"]),
        ("finance, urgent", ["finance", "urgent"]),
    ],
)
def test_upload_accepts_json_and_swagger_csv_tags(client, upload_file, encoded_tags, expected_tags):
    response = client.post(
        "/api/v1/documents/",
        {"file": upload_file(), "title": "Invoice", "tags": encoded_tags},
        format="multipart",
    )
    assert response.status_code == 201
    assert response.data["tags"] == expected_tags
    assert Document.objects.get(pk=response.data["id"]).tags == expected_tags


def test_upload_rejects_malformed_structured_tags(client, upload_file):
    response = client.post(
        "/api/v1/documents/",
        {"file": upload_file(), "title": "Invoice", "tags": '["finance",]'},
        format="multipart",
    )
    assert response.status_code == 400
    assert "tags" in response.data["error"]["details"]


@pytest.mark.parametrize(
    "name,content",
    [
        ("evil.exe", b"MZ executable"),
        ("fake.pdf", b"plain text"),
        ("fake.jpg", b"\x89PNG\r\n\x1a\nabc"),
        ("blank.png", b""),
    ],
)
def test_upload_rejects_bad_type_and_empty_file(client, name, content):
    response = client.post(
        "/api/v1/documents/",
        {"file": SimpleUploadedFile(name, content), "title": "Test"},
        format="multipart",
    )
    assert response.status_code == 400
    assert not Document.objects.exists()
    assert not Job.objects.exists()


def test_size_limit(client, upload_file, settings):
    settings.MAX_UPLOAD_BYTES = 50
    response = client.post(
        "/api/v1/documents/", {"file": upload_file(), "title": "Large"}, format="multipart"
    )
    assert response.status_code == 413


def test_upload_storage_failure_has_safe_error_and_cleanup_intent(client, upload_file):
    with patch(
        "documents.services.default_storage.save", side_effect=RuntimeError("SENSITIVE-CREDENTIAL")
    ):
        response = client.post(
            "/api/v1/documents/", {"file": upload_file(), "title": "Test"}, format="multipart"
        )
    assert response.status_code == 503
    assert "SENSITIVE-CREDENTIAL" not in str(response.data)
    assert not Document.objects.exists()
    assert Job.objects.filter(kind="delete_object", state="pending").exists()


@pytest.mark.parametrize(
    "path,method",
    [
        ("", "get"),
        ("", "patch"),
        ("", "delete"),
        ("download/", "get"),
        ("status/", "get"),
        ("text/", "get"),
        ("reprocess/", "post"),
    ],
)
def test_other_user_cannot_access_any_document_action(client, document, other_user, path, method):
    client.force_authenticate(other_user)
    response = getattr(client, method)(f"/api/v1/documents/{document.id}/{path}", {}, format="json")
    assert response.status_code == 404


def test_list_and_audit_are_owner_scoped(client, document, other_user, admin):
    client.force_authenticate(other_user)
    assert client.get("/api/v1/documents/").data["count"] == 0
    assert client.get("/api/v1/audit-events/").data["count"] == 0
    client.force_authenticate(admin)
    assert client.get("/api/v1/documents/").data["count"] == 1
    assert client.get(f"/api/v1/documents/{document.id}/").status_code == 200


def test_download_is_authorized_attachment(client, document):
    response = client.get(f"/api/v1/documents/{document.id}/download/")
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "no-store"
    assert b"".join(response.streaming_content).startswith(b"\x89PNG")


def test_metadata_patch_requires_revision_and_preserves_unsupplied_fields(client, document):
    url = f"/api/v1/documents/{document.id}/"
    assert client.patch(url, {"title": "Revised"}, format="json").status_code == 428
    response = client.patch(
        url,
        {
            "title": "Revised",
            "metadata": {"nested": {"department": "Sales"}},
            "tags": ["one", "one"],
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert response.status_code == 200
    assert response.data["revision"] == 2
    assert response.data["tags"] == ["one"]
    assert response.data["filename"] == document.filename
    assert (
        client.patch(url, {"title": "Stale"}, format="json", HTTP_IF_MATCH='"1"').status_code == 412
    )
    assert AuditEvent.objects.filter(action="metadata_updated").get().details["fields"] == [
        "metadata",
        "tags",
        "title",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"owner_id": 123},
        {"status": "succeeded"},
        {"extracted_text": "forged"},
        {"created_at": "2026-01-01"},
        {"metadata": []},
        {"metadata": {"nul": "\x00"}},
        {"metadata": {"a": "x" * 17000}},
        {"metadata": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}},
        {"tags": "not-a-list"},
        {"tags": [None]},
        {"tags": [""]},
        {"tags": ["x"] * 33},
    ],
)
def test_metadata_validation(client, document, payload):
    response = client.patch(
        f"/api/v1/documents/{document.id}/", payload, format="json", HTTP_IF_MATCH='"1"'
    )
    assert response.status_code == 400


def test_delete_removes_document_but_retains_audit_and_cleanup(client, document):
    identifier, storage_key = document.id, document.storage_key
    response = client.delete(f"/api/v1/documents/{identifier}/", HTTP_IF_MATCH='"1"')
    assert response.status_code == 204
    assert not Document.objects.filter(pk=identifier).exists()
    assert default_storage.exists(storage_key)
    assert Job.objects.filter(
        kind="delete_object", state="pending", document_id=identifier
    ).exists()
    assert AuditEvent.objects.filter(document_id=identifier, action="deleted").exists()
    assert client.get(f"/api/v1/documents/{identifier}/").status_code == 404


def test_idempotency_is_payload_sensitive_and_owner_scoped(client, upload_file, other_user):
    def post(title="Invoice"):
        return client.post(
            "/api/v1/documents/",
            {"file": upload_file(), "title": title},
            format="multipart",
            HTTP_IDEMPOTENCY_KEY="client-request-1",
        )

    first, replay = post(), post()
    assert first.status_code == 201
    assert replay.status_code == 200
    assert first.data["id"] == replay.data["id"]
    assert replay["Idempotent-Replayed"] == "true"
    assert post("Different").status_code == 409
    client.force_authenticate(other_user)
    second_owner = post()
    assert second_owner.status_code == 201
    assert second_owner.data["id"] != first.data["id"]


def test_invalid_idempotency_key(client, upload_file):
    response = client.post(
        "/api/v1/documents/",
        {"title": "Test", "file": upload_file()},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY="invalid key",
    )
    assert response.status_code == 400


def test_search_and_pagination_do_not_leak(client, upload, other_user):
    upload(title="Budget", metadata=json.dumps({"supplier": "uniquesupplier"}))
    upload(title="Report", tags='["specialtag"]')
    assert client.get("/api/v1/documents/?q=uniquesupplier").data["count"] == 1
    assert client.get("/api/v1/documents/?q=specialtag").data["count"] == 1
    page = client.get("/api/v1/documents/?page_size=1").data
    assert page["count"] == 2 and page["next"]
    assert len(page["results"]) == 1
    client.force_authenticate(other_user)
    assert client.get("/api/v1/documents/?q=uniquesupplier").data["count"] == 0


def test_search_filters_and_bad_parameters(client, document):
    assert client.get("/api/v1/documents/?status=pending").data["count"] == 1
    assert client.get("/api/v1/documents/?status=unknown").status_code == 400
    assert client.get("/api/v1/documents/", {"q": "x" * 201}).status_code == 400
    assert client.get("/api/v1/audit-events/?document_id=invalid").status_code == 400
    assert client.get("/api/v1/documents/?page=999").status_code == 404
