from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler

from core.errors import PayloadTooLarge, http_error


class RequestSizeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or "0")
        except ValueError:
            return http_error(request, 400, "bad_request", "Invalid Content-Length.")
        if length < 0:
            return http_error(request, 400, "bad_request", "Invalid Content-Length.")
        if length > settings.MAX_UPLOAD_BYTES + 64 * 1024:
            return http_error(
                request, 413, "payload_too_large", "The request exceeds the configured size limit."
            )
        return self.get_response(request)


class BoundedUploadHandler(FileUploadHandler):
    """Enforce the streaming byte limit even without a trustworthy Content-Length."""

    def __init__(self, request=None):
        super().__init__(request)
        self.total = 0

    def receive_data_chunk(self, raw_data, start):
        self.total += len(raw_data)
        if self.total > settings.MAX_UPLOAD_BYTES:
            raise PayloadTooLarge()
        return raw_data

    def file_complete(self, file_size):
        return None
