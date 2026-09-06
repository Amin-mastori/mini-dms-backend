import io

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw, ImageFont
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def isolated_storage(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    cache.clear()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("alice", password="correct-test-password-29")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user("bob", password="correct-test-password-72")


@pytest.fixture
def admin(db):
    return get_user_model().objects.create_user(
        "admin", password="correct-test-password-41", is_staff=True
    )


@pytest.fixture
def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def png_bytes(text="MINI DMS INVOICE 2026"):
    stream = io.BytesIO()
    image = Image.new("RGB", (1200, 300), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 48)
    except OSError:
        font = ImageFont.load_default(size=48)
    draw.text((40, 100), text, fill="black", font=font)
    image.save(stream, "PNG")
    image.close()
    return stream.getvalue()


@pytest.fixture
def upload_file():
    return lambda: SimpleUploadedFile("invoice.png", png_bytes(), content_type="image/png")


@pytest.fixture
def upload(client, upload_file):
    def create(**kwargs):
        payload = {"file": upload_file(), "title": "Quarterly invoice", **kwargs}
        response = client.post("/api/v1/documents/", payload, format="multipart")
        assert response.status_code == 201, response.data
        return response

    return create


@pytest.fixture
def document(upload):
    from documents.models import Document

    return Document.objects.get(pk=upload().data["id"])
