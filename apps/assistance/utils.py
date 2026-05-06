import os

from django.conf import settings
from django.core.exceptions import ValidationError


def validate_file_upload(uploaded_file) -> None:
    """Validate citizen-uploaded supporting documents."""
    allowed = getattr(
        settings,
        "TRACEPOINT_UPLOAD_ALLOWED_EXTENSIONS",
        (".pdf",),
    )
    max_mb = int(getattr(settings, "TRACEPOINT_UPLOAD_MAX_SIZE_MB", 5))

    ext = os.path.splitext(getattr(uploaded_file, "name", "") or "")[1].lower()
    if ext not in allowed:
        raise ValidationError(f"Unsupported file type: {ext or '(none)'}")

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > max_mb * 1024 * 1024:
        raise ValidationError(f"File size exceeds {max_mb}MB.")
