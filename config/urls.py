from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import SimpleRouter

from accounts.views import LoginView, LogoutView, MeView, RefreshView, UserListCreateView
from core.health import LiveView, ReadyView
from documents.views import AuditListView, DocumentViewSet, JobListView

router = SimpleRouter()
router.register("documents", DocumentViewSet, basename="document")

urlpatterns = [
    path("health/live/", LiveView.as_view(), name="health-live"),
    path("health/ready/", ReadyView.as_view(), name="health-ready"),
    path("api/v1/auth/token/", LoginView.as_view(), name="token-obtain"),
    path("api/v1/auth/token/refresh/", RefreshView.as_view(), name="token-refresh"),
    path("api/v1/auth/logout/", LogoutView.as_view(), name="token-logout"),
    path("api/v1/auth/me/", MeView.as_view(), name="me"),
    path("api/v1/admin/users/", UserListCreateView.as_view(), name="users"),
    path("api/v1/admin/jobs/", JobListView.as_view(), name="jobs"),
    path("api/v1/audit-events/", AuditListView.as_view(), name="audit-events"),
    path("api/v1/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

handler400 = "core.errors.bad_request"
handler404 = "core.errors.not_found"
handler500 = "core.errors.server_error"
