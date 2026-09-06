import logging
import re
import uuid

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.files.storage import default_storage
from django.db import connection, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import generics, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle

from core.errors import ServiceUnavailable
from documents import services
from documents.models import AuditEvent, Document, Job, normalize_text
from documents.serializers import (
    AuditSerializer,
    DocumentListSerializer,
    DocumentSerializer,
    JobSerializer,
    MetadataSerializer,
    OCRTextSerializer,
    ProcessingStatusSerializer,
    UploadSerializer,
    validate_idempotency_key,
)

logger = logging.getLogger("dms.downloads")
IF_MATCH = OpenApiParameter(
    "If-Match",
    str,
    OpenApiParameter.HEADER,
    required=True,
    description='Current metadata revision, quoted: "1".',
)


class DocumentViewSet(viewsets.GenericViewSet):
    serializer_class = DocumentSerializer
    parser_classes = [JSONParser, MultiPartParser]
    lookup_value_regex = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

    def get_throttles(self):
        self.throttle_scope = {"create": "upload", "reprocess": "reprocess"}.get(self.action)
        return (
            [UserRateThrottle(), ScopedRateThrottle()]
            if self.throttle_scope
            else [UserRateThrottle()]
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Document.objects.none()
        return services.scoped_documents(self.request.user).defer(
            "search_text", "search_vector", "extracted_text"
        )

    def document_response(self, document, response_status=200):
        return Response(
            DocumentSerializer(document).data,
            status=response_status,
            headers={"ETag": f'"{document.revision}"'},
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "q", str, description="Token-based full-text query, up to 200 characters."
            ),
            OpenApiParameter("status", str, enum=list(Document.Status.values)),
            OpenApiParameter("document_type", str),
            OpenApiParameter("tag", str, description="Exact, case-sensitive tag filter."),
        ],
        responses=DocumentListSerializer(many=True),
        tags=["Documents"],
    )
    def list(self, request):
        queryset = self.get_queryset()
        query = request.query_params.get("q", "").strip()
        if "\x00" in query:
            raise serializers.ValidationError({"q": "NUL characters are not allowed."})
        if len(query) > 200:
            raise serializers.ValidationError({"q": "Maximum length is 200 characters."})
        if query:
            if connection.vendor == "postgresql":
                search = SearchQuery(
                    normalize_text(query), search_type="websearch", config="simple"
                )
                queryset = (
                    queryset.filter(search_vector=search)
                    .annotate(rank=SearchRank("search_vector", search))
                    .order_by("-rank", "-created_at", "-id")
                )
            elif settings.TESTING:
                # Portable contract tests only; PostgreSQL semantics have separate tests.
                for term in normalize_text(query).split():
                    queryset = queryset.filter(search_text__icontains=term)
            else:
                raise ServiceUnavailable()
        if document_status := request.query_params.get("status"):
            if document_status not in Document.Status.values:
                raise serializers.ValidationError({"status": "Unknown processing status."})
            queryset = queryset.filter(status=document_status)
        if document_type := request.query_params.get("document_type"):
            if len(document_type) > 64 or "\x00" in document_type:
                raise serializers.ValidationError(
                    {"document_type": "Use at most 64 characters without NUL."}
                )
            queryset = queryset.filter(document_type=document_type)
        if tag := request.query_params.get("tag"):
            if len(tag) > 64 or "\x00" in tag:
                raise serializers.ValidationError({"tag": "Use at most 64 characters without NUL."})
            if connection.vendor == "postgresql":
                queryset = queryset.filter(tags__contains=[tag])
            else:
                raise serializers.ValidationError(
                    {"tag": "Exact tag filtering requires PostgreSQL."}
                )
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(DocumentListSerializer(page, many=True).data)

    @extend_schema(
        request=UploadSerializer,
        responses={201: DocumentSerializer, 200: DocumentSerializer},
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER)],
        tags=["Documents"],
    )
    def create(self, request):
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = validate_idempotency_key(request.headers.get("Idempotency-Key"))
        document, created = services.create_document(
            request.user, serializer.validated_data, key, request.request_id
        )
        response = self.document_response(document, 201 if created else 200)
        response["Location"] = f"/api/v1/documents/{document.id}/"
        if not created:
            response["Idempotent-Replayed"] = "true"
        return response

    @extend_schema(responses=DocumentSerializer, tags=["Documents"])
    def retrieve(self, request, pk=None):
        return self.document_response(self.get_object())

    @extend_schema(
        request=MetadataSerializer,
        responses=DocumentSerializer,
        parameters=[IF_MATCH],
        tags=["Documents"],
    )
    @transaction.atomic
    def partial_update(self, request, pk=None):
        document = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
        serializer = MetadataSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = services.update_document(
            document,
            serializer.validated_data,
            request.user,
            request.request_id,
            request.headers.get("If-Match"),
        )
        return self.document_response(updated)

    @extend_schema(responses={204: None}, parameters=[IF_MATCH], tags=["Documents"])
    @transaction.atomic
    def destroy(self, request, pk=None):
        document = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
        services.delete_document(
            document, request.user, request.request_id, request.headers.get("If-Match")
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses=ProcessingStatusSerializer, tags=["Processing"])
    @action(detail=True, methods=["get"], url_path="status")
    def processing_status(self, request, pk=None):
        return Response(ProcessingStatusSerializer(self.get_object()).data)

    @extend_schema(responses=OCRTextSerializer, tags=["Processing"])
    @action(detail=True, methods=["get"], url_path="text")
    def text(self, request, pk=None):
        document = self.get_object()
        return Response(
            {"id": str(document.id), "status": document.status, "text": document.extracted_text}
        )

    @extend_schema(
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY}, tags=["Documents"]
    )
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        document = self.get_object()
        try:
            stream = default_storage.open(document.storage_key, "rb")
        except Exception as exc:
            logger.exception("download_unavailable", extra={"document_id": str(document.id)})
            raise ServiceUnavailable() from exc
        response = FileResponse(
            stream, as_attachment=True, filename=document.filename, content_type=document.mime_type
        )
        response["Content-Length"] = str(document.size)
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @extend_schema(
        request=None,
        responses={202: DocumentSerializer},
        parameters=[IF_MATCH],
        tags=["Processing"],
    )
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reprocess(self, request, pk=None):
        document = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
        result = services.reprocess_document(
            document, request.user, request.request_id, request.headers.get("If-Match")
        )
        return self.document_response(result, 202)


class AuditListView(generics.ListAPIView):
    serializer_class = AuditSerializer

    def get_queryset(self):
        queryset = AuditEvent.objects.all()
        if not self.request.user.is_staff:
            queryset = queryset.filter(owner=self.request.user)
        if identifier := self.request.query_params.get("document_id"):
            try:
                identifier = uuid.UUID(identifier)
            except ValueError as exc:
                raise serializers.ValidationError({"document_id": "Use a valid UUID."}) from exc
            queryset = queryset.filter(document_id=identifier)
        return queryset


class JobListView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = JobSerializer

    def get_queryset(self):
        queryset = Job.objects.order_by("-created_at", "-id")
        if state := self.request.query_params.get("state"):
            if state not in Job.State.values:
                raise serializers.ValidationError({"state": "Unknown job state."})
            queryset = queryset.filter(state=state)
        if correlation := self.request.query_params.get("request_id"):
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", correlation):
                raise serializers.ValidationError({"request_id": "Use a valid UUID."})
            try:
                queryset = queryset.filter(request_id=uuid.UUID(correlation))
            except ValueError as exc:
                raise serializers.ValidationError({"request_id": "Use a valid UUID."}) from exc
        return queryset
