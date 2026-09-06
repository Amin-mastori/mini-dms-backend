"""Real HTTP -> private S3 -> Redis -> Celery -> PostgreSQL acceptance check.

Run against a disposable evaluation deployment. Creates two short-lived test
accounts (kept for audit attribution) and deletes its uploaded documents.
"""

import argparse
import getpass
import io
import os
import secrets
import time
import uuid

import requests
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas


def require(response, expected):
    if response.status_code != expected:
        correlation = response.headers.get("X-Request-ID", "unknown")
        raise RuntimeError(
            f"Expected HTTP {expected}, got {response.status_code}; request_id={correlation}"
        )
    return response.json() if response.content and expected != 204 else {}


def make_image():
    stream = io.BytesIO()
    image = Image.new("RGB", (1200, 300), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 48)
    except OSError:
        font = ImageFont.load_default(size=48)
    draw.text((40, 100), "MINI DMS INVOICE 2026", fill="black", font=font)
    image.save(stream, "PNG")
    return stream.getvalue()


def run(base, username, password):
    def call(method, path, **kwargs):
        return requests.request(method, base.rstrip("/") + path, timeout=30, **kwargs)

    def login(name, secret):
        tokens = require(
            call("POST", "/api/v1/auth/token/", json={"username": name, "password": secret}), 200
        )
        return {"Authorization": "Bearer " + tokens["access"]}

    admin = login(username, password)
    require(call("GET", "/health/ready/", headers=admin), 200)
    marker = uuid.uuid4().hex[:10]
    users = []
    for suffix in ("a", "b"):
        name, secret = f"smoke_{marker}_{suffix}", secrets.token_urlsafe(24)
        require(
            call(
                "POST",
                "/api/v1/admin/users/",
                headers=admin,
                json={"username": name, "password": secret},
            ),
            201,
        )
        users.append(login(name, secret))
    owner, stranger = users
    artifacts = []
    try:
        uploads = [("invoice.png", make_image(), "image/png", "INVOICE")]
        pdf = io.BytesIO()
        writer = canvas.Canvas(pdf)
        writer.drawString(60, 750, "Native document finance acceptance")
        writer.save()
        uploads.append(("report.pdf", pdf.getvalue(), "application/pdf", "finance"))
        # A scanned PDF tests the real PDF render -> Tesseract path too.
        scanned = io.BytesIO()
        with Image.open(io.BytesIO(make_image())) as image:
            image.convert("RGB").save(scanned, "PDF", resolution=150)
        uploads.append(("scan.pdf", scanned.getvalue(), "application/pdf", "INVOICE"))
        jpeg = io.BytesIO()
        with Image.open(io.BytesIO(make_image())) as image:
            image.save(jpeg, "JPEG")
        uploads.append(("image.jpg", jpeg.getvalue(), "image/jpeg", "INVOICE"))

        for name, content, mime, expected_text in uploads:
            headers = {**owner, "Idempotency-Key": f"{marker}-{name}"}
            payload = {
                "title": f"Acceptance {marker}",
                "metadata": '{"department":"finance"}',
                "tags": '["acceptance"]',
            }
            response = call(
                "POST",
                "/api/v1/documents/",
                headers=headers,
                data=payload,
                files={"file": (name, content, mime)},
            )
            document = require(response, 201)
            path = f"/api/v1/documents/{document['id']}/"
            artifacts.append(path)
            repeated = require(
                call(
                    "POST",
                    "/api/v1/documents/",
                    headers=headers,
                    data=payload,
                    files={"file": (name, content, mime)},
                ),
                200,
            )
            assert repeated["id"] == document["id"]
            for endpoint in (path, path + "text/", path + "status/", path + "download/"):
                require(call("GET", endpoint, headers=stranger), 404)
            require(call("PATCH", path, headers=stranger, json={"title": "Intrusion"}), 404)
            require(call("DELETE", path, headers=stranger), 404)
            deadline = time.monotonic() + 240
            while True:
                state = require(call("GET", path + "status/", headers=owner), 200)
                if state["status"] in ("succeeded", "failed"):
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Processing timeout; document_id={document['id']}")
                time.sleep(2)
            if state["status"] != "succeeded":
                raise RuntimeError(
                    f"OCR failed: {state['error_code']}; document_id={document['id']}"
                )
            text = require(call("GET", path + "text/", headers=owner), 200)["text"]
            assert expected_text.lower() in text.lower()
            download = call("GET", path + "download/", headers=owner)
            assert download.status_code == 200 and download.content == content
            updated = require(
                call(
                    "PATCH",
                    path,
                    headers={**owner, "If-Match": '"1"'},
                    json={"title": f"Updated {marker}"},
                ),
                200,
            )
            assert updated["revision"] == 2
            require(
                call("PATCH", path, headers={**owner, "If-Match": '"1"'}, json={"title": "stale"}),
                412,
            )
        results = require(
            call("GET", "/api/v1/documents/", headers=owner, params={"q": marker, "page_size": 2}),
            200,
        )
        assert results["count"] == 4 and results["next"]
        assert (
            require(call("GET", "/api/v1/documents/", headers=stranger, params={"q": marker}), 200)[
                "count"
            ]
            == 0
        )
        assert require(call("GET", "/api/v1/audit-events/", headers=stranger), 200)["count"] == 0
        print(
            "PASS: real PNG, JPEG, native PDF and scanned PDF extraction; owner isolation; idempotency; search; pagination; revision protection."
        )
    finally:
        for path in artifacts:
            current = call("GET", path, headers=owner)
            if current.status_code == 200:
                revision = current.json()["revision"]
                require(call("DELETE", path, headers={**owner, "If-Match": f'"{revision}"'}), 204)
                require(call("GET", path, headers=owner), 404)
        if artifacts:
            identifier = artifacts[-1].strip("/").rsplit("/", 1)[-1]
            events = require(
                call(
                    "GET",
                    "/api/v1/audit-events/",
                    headers=owner,
                    params={"document_id": identifier},
                ),
                200,
            )
            assert any(event["action"] == "deleted" for event in events["results"])
            print(
                "PASS: uploaded test documents deleted; audit history retained. Test accounts remain for attribution."
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://api:8000")
    parser.add_argument("--username", default=os.environ.get("SMOKE_USERNAME", "admin"))
    args = parser.parse_args()
    password = os.environ.get("SMOKE_PASSWORD") or getpass.getpass("Administrator password: ")
    run(args.base_url, args.username, password)


if __name__ == "__main__":
    main()
