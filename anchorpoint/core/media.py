"""Serve uploaded media with access control.

Everything under MEDIA_ROOT used to be public to anyone who could guess a
filename, including photos of minors. Now only folders that must be public
are open; everything else requires a staff login.

Public on purpose:
- organization/logo/          shown on public pages and emails
- events/photos/              public event pages
- events/releases/            release templates linked from public registration
- communications/phone_blasts/ Twilio fetches the audio (names are random UUIDs)
"""
import mimetypes
import posixpath

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.views.static import serve

from core.permissions import is_staff_or_above

PUBLIC_PREFIXES = (
    "organization/logo/",
    "events/photos/",
    "events/releases/",
    "communications/phone_blasts/",
)

# Served inline; anything else is forced to download in a sandbox so an
# uploaded .html/.svg can never run script on this origin.
INLINE_SAFE_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "audio/webm",
    "audio/mp4", "video/mp4", "application/pdf",
}


def serve_media(request, path):
    normalized = posixpath.normpath(path).lstrip("/")
    if not normalized.startswith(PUBLIC_PREFIXES):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_staff_or_above(request.user):
            return HttpResponseForbidden("You do not have permission to view this file.")

    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    content_type = (mimetypes.guess_type(normalized)[0] or "").lower()
    if content_type not in INLINE_SAFE_TYPES:
        filename = posixpath.basename(normalized).replace('"', "")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Content-Security-Policy"] = "sandbox"
    if not normalized.startswith(PUBLIC_PREFIXES):
        response["Cache-Control"] = "private, no-store"
    return response
