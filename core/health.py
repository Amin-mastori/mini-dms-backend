from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    checks = serializers.DictField(required=False)


class LiveView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    @extend_schema(responses=HealthSerializer, tags=["Operations"])
    def get(self, request):
        return Response({"status": "ok"})


class ReadyView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_classes = []

    @extend_schema(responses={200: HealthSerializer, 503: HealthSerializer}, tags=["Operations"])
    def get(self, request):
        checks = {}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable"
        try:
            cache.set("dms:ready", "ok", 15)
            checks["redis"] = "ok" if cache.get("dms:ready") == "ok" else "unavailable"
        except Exception:
            checks["redis"] = "unavailable"
        try:
            # HEAD a random absent key validates connectivity, not public access.
            default_storage.exists("health/ready-probe")
            checks["storage"] = "ok"
        except Exception:
            checks["storage"] = "unavailable"
        healthy = all(value == "ok" for value in checks.values())
        return Response(
            {"status": "ready" if healthy else "degraded", "checks": checks},
            status=200 if healthy else 503,
        )
