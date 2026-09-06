import os
from datetime import timedelta
from pathlib import Path

from botocore.config import Config
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
TESTING = os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings.test"
if not SECRET_KEY and not TESTING:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY; run scripts/init_env.py for development.")
if not TESTING and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must contain at least 50 characters.")
DEBUG = False
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,api").split(",")
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "storages",
    "accounts",
    "core",
    "documents",
]
MIDDLEWARE = [
    "core.observability.RequestContextMiddleware",
    "core.uploads.RequestSizeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "dms"),
        "USER": os.environ.get("POSTGRES_USER", "dms"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": 5,
            "options": "-c statement_timeout=15000 -c lock_timeout=5000",
        },
    }
}
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
# Throttling uses a separate logical DB but shares the development Redis instance.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_CACHE_URL", "redis://redis:6379/1"),
        "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
    }
}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = False
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DocumentPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.errors.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "user": "300/min",
        "login": "10/min",
        "upload": "30/hour",
        "reprocess": "30/hour",
    },
    "NUM_PROXIES": 0,
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "SIGNING_KEY": os.environ.get("JWT_SIGNING_KEY", SECRET_KEY),
    "ALGORITHM": "HS256",
    "ISSUER": "mini-dms",
    "AUDIENCE": "mini-dms-api",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Mini DMS API",
    "DESCRIPTION": "Private document management with asynchronous extraction and recoverable jobs.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "COMPONENT_SPLIT_REQUEST": True,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "core.schema.add_error_contract",
    ],
}
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "access_key": os.environ.get("S3_ACCESS_KEY", ""),
            "secret_key": os.environ.get("S3_SECRET_KEY", ""),
            "bucket_name": os.environ.get("S3_BUCKET", "documents"),
            "endpoint_url": os.environ.get("S3_ENDPOINT_URL") or None,
            "region_name": os.environ.get("S3_REGION", "us-east-1"),
            "signature_version": "s3v4",
            "addressing_style": os.environ.get("S3_ADDRESSING_STYLE", "path"),
            "default_acl": None,
            "file_overwrite": False,
            "querystring_auth": True,
            "max_memory_size": 1024 * 1024,
            "client_config": Config(
                connect_timeout=3,
                read_timeout=15,
                retries={"max_attempts": 2},
                signature_version="s3v4",
                s3={"addressing_style": os.environ.get("S3_ADDRESSING_STYLE", "path")},
            ),
        },
    }
}
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 25 * 1024 * 1024))
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
FILE_UPLOAD_HANDLERS = [
    "core.uploads.BoundedUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]
DATA_UPLOAD_MAX_NUMBER_FIELDS = 16
DATA_UPLOAD_MAX_NUMBER_FILES = 1
MAX_OCR_PAGES = int(os.environ.get("MAX_OCR_PAGES", 20))
MAX_OCR_PIXELS = int(os.environ.get("MAX_OCR_PIXELS", 20_000_000))
MAX_OCR_CHARS = int(os.environ.get("MAX_OCR_CHARS", 200_000))
OCR_LANGUAGES = os.environ.get("OCR_LANGUAGES", "eng+fas")
OCR_PAGE_TIMEOUT = int(os.environ.get("OCR_PAGE_TIMEOUT", 45))
JOB_LEASE_SECONDS = 240
JOB_REDISPATCH_SECONDS = 30
CELERY_BROKER_URL = REDIS_URL
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = 170
CELERY_TASK_TIME_LIMIT = 180
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": 300,
    "socket_connect_timeout": 3,
    "socket_timeout": 3,
}
CELERY_TASK_PUBLISH_RETRY = False
CELERY_TASK_DEFAULT_QUEUE = "documents"
CELERY_WORKER_MAX_TASKS_PER_CHILD = 30
CELERY_WORKER_MAX_MEMORY_PER_CHILD = 600000
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 0))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Enable only behind a trusted proxy that strips user-supplied forwarding headers.
if os.environ.get("TRUST_PROXY_HEADERS", "false").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "core.observability.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {
        "dms": {"level": "INFO"},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "botocore": {"level": "WARNING"},
        "celery": {"level": "WARNING"},
    },
}
