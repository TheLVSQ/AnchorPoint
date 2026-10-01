"""Upload validators shared by models with FileField/ImageField."""
import os
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

MAX_IMAGE_BYTES = 5 * 1024 * 1024

pdf_extension = FileExtensionValidator(["pdf"])


def _already_stored(file):
    """True for a file already saved before (e.g. re-saving a form without a new
    upload). Rules apply to new uploads only, so legacy files keep working."""
    return getattr(file, "_committed", False) and getattr(file, "name", "")


def validate_pdf(file):
    """Release documents must be real PDFs: an uploaded .html/.svg served from
    this origin could run script as whoever opens it."""
    if _already_stored(file):
        return
    pdf_extension(file)
    pos = file.tell() if hasattr(file, "tell") else 0
    try:
        file.seek(0)
        header = file.read(5)
    finally:
        try:
            file.seek(pos)
        except Exception:
            pass
    if header != b"%PDF-":
        raise ValidationError("Please upload a PDF file.")


def validate_image_size(file):
    if _already_stored(file):
        return
    if file.size and file.size > MAX_IMAGE_BYTES:
        raise ValidationError("Images must be 5 MB or smaller.")


def person_photo_upload_path(instance, filename):
    """Random, unguessable names for people's photos (many are minors)."""
    ext = os.path.splitext(filename)[1].lower()[:10] or ".jpg"
    return f"people/photos/{uuid.uuid4().hex}{ext}"
