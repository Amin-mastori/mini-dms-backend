import hashlib
import json
import re
import unicodedata

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.errors import PayloadTooLarge
from core.serializers import StrictInputMixin
from documents.models import AuditEvent, Document, Job


def json_depth(value):
    if isinstance(value, dict):
        return 1 + max((json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((json_depth(item) for item in value), default=0)
    return 0


@extend_schema_field(
    {"type": "array", "items": {"type": "string", "maxLength": 64}, "maxItems": 32}
)
class TagsField(serializers.JSONField):
    pass


@extend_schema_field({"type": "object", "additionalProperties": {}})
class JSONObjectField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "string",
        "description": "JSON array encoded as a multipart text field.",
        "example": '["test","invoice"]',
    }
)
class MultipartTagsField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "string",
        "description": "JSON object encoded as a multipart text field.",
        "example": '{"department":"finance","year":2026}',
    }
)
class MultipartJSONObjectField(serializers.JSONField):
    pass


class MetadataSerializer(StrictInputMixin, serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=10000, allow_blank=True, default="")
    document_type = serializers.CharField(max_length=64, allow_blank=True, default="")
    tags = TagsField(default=list)
    metadata = JSONObjectField(default=dict)

    def validate_tags(self, value):
        if not isinstance(value, list) or len(value) > 32:
            raise serializers.ValidationError("Use a list of at most 32 tags.")
        if any(
            not isinstance(tag, str) or not 1 <= len(tag.strip()) <= 64 or "\x00" in tag
            for tag in value
        ):
            raise serializers.ValidationError("Each tag must contain 1 to 64 characters.")
        return list(dict.fromkeys(tag.strip() for tag in value))

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Metadata must be a JSON object.")
        try:
            encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        except (ValueError, TypeError) as exc:
            raise serializers.ValidationError(
                "Metadata must contain valid finite JSON values."
            ) from exc
        if "\\u0000" in encoded:
            raise serializers.ValidationError("Metadata cannot contain NUL characters.")
        if len(encoded.encode()) > 16384 or json_depth(value) > 5:
            raise serializers.ValidationError(
                "Metadata is limited to 16 KiB and five nesting levels."
            )
        return value


class UploadSerializer(MetadataSerializer):
    tags = MultipartTagsField(default=list)
    metadata = MultipartJSONObjectField(default=dict)
    file = serializers.FileField(write_only=True, allow_empty_file=False)

    def validate_file(self, upload):
        if upload.size > settings.MAX_UPLOAD_BYTES:
            raise PayloadTooLarge()
        name = upload.name.replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(c for c in name if not unicodedata.category(c).startswith("C"))
        if not name or len(name) > 255:
            raise serializers.ValidationError("Use a filename of 1 to 255 characters.")
        extension = name.rsplit(".", 1)[-1].lower()
        head = upload.read(1024)
        upload.seek(0)
        detected = None
        if head.startswith(b"%PDF-"):
            detected = "application/pdf"
        elif head.startswith(b"\x89PNG\r\n\x1a\n"):
            detected = "image/png"
        elif head.startswith(b"\xff\xd8\xff"):
            detected = "image/jpeg"
        expected = {
            "pdf": "application/pdf",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
        }
        if detected is None or expected.get(extension) != detected:
            raise serializers.ValidationError(
                "Only PDF, JPEG and PNG with matching file signatures are accepted."
            )
        digest = hashlib.sha256()
        total = 0
        for chunk in upload.chunks():
            total += len(chunk)
            if total > settings.MAX_UPLOAD_BYTES:
                raise PayloadTooLarge()
            digest.update(chunk)
        upload.seek(0)
        upload.name = name
        upload.detected_type = detected
        upload.content_type = detected
        upload.sha256 = digest.hexdigest()
        if total != upload.size:
            raise serializers.ValidationError("Invalid upload size.")
        return upload


class DocumentSerializer(serializers.ModelSerializer):
    tags = TagsField(read_only=True)
    metadata = JSONObjectField(read_only=True)
    processing_info = JSONObjectField(read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "owner_id",
            "filename",
            "mime_type",
            "size",
            "sha256",
            "title",
            "description",
            "document_type",
            "tags",
            "metadata",
            "created_at",
            "updated_at",
            "revision",
            "status",
            "attempts",
            "processed_at",
            "error_code",
            "error_message",
            "processing_info",
        ]
        read_only_fields = fields


class DocumentListSerializer(serializers.ModelSerializer):
    tags = TagsField(read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "filename",
            "mime_type",
            "size",
            "document_type",
            "tags",
            "status",
            "revision",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProcessingStatusSerializer(serializers.ModelSerializer):
    processing_info = JSONObjectField(read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "status",
            "attempts",
            "error_code",
            "error_message",
            "processed_at",
            "processing_info",
        ]
        read_only_fields = fields


class OCRTextSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    text = serializers.CharField(allow_blank=True)


class AuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "document_id",
            "owner_id",
            "actor_id",
            "actor_kind",
            "action",
            "request_id",
            "details",
            "created_at",
        ]
        read_only_fields = fields


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = [
            "id",
            "document_id",
            "kind",
            "state",
            "attempts",
            "max_attempts",
            "available_at",
            "lease_until",
            "request_id",
            "error_code",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


def validate_idempotency_key(key):
    if key is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        raise serializers.ValidationError(
            {
                "Idempotency-Key": "Use 1 to 128 ASCII letters, digits, dots, underscores, colons or hyphens."
            }
        )
    return key
