# syntax=docker/dockerfile:1
FROM minio/mc:RELEASE.2025-08-13T08-35-41Z AS minio-client
FROM python:3.12.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 OMP_THREAD_LIMIT=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-fas curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 dms && useradd --uid 10001 --gid dms --create-home dms
COPY requirements.txt ./
RUN pip install --require-hashes -r requirements.txt
COPY --chown=dms:dms . .
USER dms
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "120", "--max-requests", "1000", "--max-requests-jitter", "100"]

FROM runtime AS storage-init
COPY --from=minio-client /usr/bin/mc /usr/local/bin/mc
CMD ["python", "scripts/init_storage.py"]

FROM runtime AS test
USER root
COPY requirements-dev.txt ./
RUN pip install --require-hashes -r requirements-dev.txt
USER dms
CMD ["pytest", "--cov", "--cov-report=term-missing"]
