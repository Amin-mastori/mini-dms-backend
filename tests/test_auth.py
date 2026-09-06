import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_anonymous_cannot_access_documents():
    response = APIClient().get("/api/v1/documents/")
    assert response.status_code == 401
    assert response.data["error"]["code"] == "not_authenticated"


def test_login_refresh_rotation_logout(user):
    client = APIClient()
    login = client.post(
        "/api/v1/auth/token/",
        {"username": user.username, "password": "correct-test-password-29"},
        format="json",
    )
    assert login.status_code == 200
    old_refresh = login.data["refresh"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    assert client.get("/api/v1/auth/me/").data["role"] == "user"
    rotated = client.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh}, format="json")
    assert rotated.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/token/refresh/", {"refresh": old_refresh}, format="json"
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/logout/", {"refresh": rotated.data["refresh"]}, format="json"
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/token/refresh/", {"refresh": rotated.data["refresh"]}, format="json"
        ).status_code
        == 401
    )


def test_wrong_password_and_disabled_user(user):
    client = APIClient()
    assert (
        client.post(
            "/api/v1/auth/token/", {"username": user.username, "password": "wrong"}, format="json"
        ).status_code
        == 401
    )
    user.is_active = False
    user.save()
    assert (
        client.post(
            "/api/v1/auth/token/",
            {"username": user.username, "password": "correct-test-password-29"},
            format="json",
        ).status_code
        == 401
    )


def test_invalid_bearer_token():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer forged-token")
    assert client.get("/api/v1/documents/").status_code == 401


@pytest.mark.parametrize(
    "endpoint", ["/api/v1/admin/users/", "/api/v1/admin/jobs/", "/health/ready/"]
)
def test_regular_user_cannot_use_admin_endpoints(client, endpoint):
    assert client.get(endpoint).status_code == 403


def test_only_admin_can_provision_user(client, admin):
    payload = {"username": "newuser", "password": "secure-passphrase-example-27", "role": "user"}
    assert client.post("/api/v1/admin/users/", payload, format="json").status_code == 403
    client.force_authenticate(admin)
    response = client.post("/api/v1/admin/users/", payload, format="json")
    assert response.status_code == 201
    assert response.data["role"] == "user"
    assert "password" not in response.data


@pytest.mark.parametrize("extra", [{"password": "123"}, {"is_superuser": True}, {"owner_id": 1}])
def test_provisioning_rejects_weak_password_and_unknown_fields(client, admin, extra):
    client.force_authenticate(admin)
    payload = {"username": "newuser", "password": "long-example-password-14", **extra}
    assert client.post("/api/v1/admin/users/", payload, format="json").status_code == 400


def test_login_throttling(user):
    client = APIClient()
    responses = [
        client.post(
            "/api/v1/auth/token/", {"username": "alice", "password": "wrong"}, format="json"
        )
        for _ in range(11)
    ]
    assert responses[-1].status_code == 429
    assert "Retry-After" in responses[-1]
