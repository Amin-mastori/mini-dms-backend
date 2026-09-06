import os
import tempfile

from config.settings.base import *

SECRET_KEY = "test-only-secret-key-with-sufficient-length-not-for-deployment"
SIMPLE_JWT = {**SIMPLE_JWT, "SIGNING_KEY": SECRET_KEY}
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
if os.environ.get("TEST_POSTGRES") != "1":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
MEDIA_ROOT = tempfile.gettempdir() + "/mini-dms-test-media"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
OCR_LANGUAGES = "eng"
CELERY_BROKER_URL = "memory://"
