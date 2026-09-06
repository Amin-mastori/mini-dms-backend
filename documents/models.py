import json
import unicodedata
import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.utils import timezone


def normalize_text(value):
    return (
        unicodedata.normalize("NFKC", value)
        .translate({0x064A: 0x06CC, 0x0643: 0x06A9, 0x200C: 0x20})
        .casefold()
    )


class Document(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    storage_key = models.CharField(max_length=512, unique=True, editable=False)
    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=64)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    document_type = models.CharField(max_length=64, blank=True, default="")
    tags = models.JSONField(default=list)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    revision = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    extracted_text = models.TextField(blank=True, default="")
    processing_info = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.CharField(max_length=255, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, null=True, blank=True, editable=False)
    request_fingerprint = models.CharField(max_length=64, blank=True, editable=False)
    search_text = models.TextField(default="", editable=False)
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="unique_owner_upload_key",
            ),
            models.CheckConstraint(condition=Q(size__gt=0), name="document_size_positive"),
        ]
        indexes = [
            models.Index(fields=["owner", "-created_at", "-id"], name="doc_owner_created_idx"),
            models.Index(fields=["status", "created_at"], name="doc_status_created_idx"),
            GinIndex(fields=["search_vector"], name="doc_search_gin"),
        ]

    def save(self, *args, **kwargs):
        self.search_text = normalize_text(
            " ".join(
                [
                    self.title,
                    self.description,
                    self.document_type,
                    json.dumps(self.tags, ensure_ascii=False),
                    json.dumps(self.metadata, ensure_ascii=False),
                    self.extracted_text,
                ]
            )
        )
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"search_text", "updated_at"}
        super().save(*args, **kwargs)


class Job(models.Model):
    class Kind(models.TextChoices):
        OCR = "ocr"
        DELETE = "delete_object"

    class State(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Snapshot identifiers intentionally survive document deletion.
    document_id = models.UUIDField(null=True, blank=True, db_index=True)
    kind = models.CharField(max_length=16, choices=Kind)
    storage_key = models.CharField(max_length=512, blank=True)
    state = models.CharField(max_length=16, choices=State, default=State.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    available_at = models.DateTimeField(default=timezone.now)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    run_token = models.UUIDField(null=True, blank=True)
    request_id = models.UUIDField(default=uuid.uuid4)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["state", "available_at"], name="job_dispatch_idx")]


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_id = models.UUIDField(db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="document_audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="performed_audit_events",
    )
    actor_kind = models.CharField(max_length=16, default="user")
    action = models.CharField(max_length=32)
    request_id = models.UUIDField(default=uuid.uuid4)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["owner", "-created_at"], name="audit_owner_created_idx")]
