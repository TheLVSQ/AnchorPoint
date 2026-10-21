"""Content preparation for outbound communications: phone-blast audio + public base URL."""
import logging
import os
import shutil
import subprocess
import tempfile
import uuid

from django.conf import settings as django_settings
from django.core.files.base import ContentFile

from core.models import OrganizationSettings

logger = logging.getLogger(__name__)


class AudioProcessingError(Exception):
    """Raised when an uploaded/recorded audio file cannot be transcoded."""


def get_site_base_url(settings_obj: OrganizationSettings | None = None) -> str | None:
    """Return the public base URL for building absolute audio/callback URLs.

    Used by headless contexts (the scheduled-delivery management command) that
    have no request to derive an absolute URL from. Resolution order:

    1. ``SITE_BASE_URL`` Django setting / env var
    2. ``OrganizationSettings.website``
    3. first entry of ``CSRF_TRUSTED_ORIGINS``

    Returns ``None`` (and logs a warning) when nothing is configured.
    """
    settings_obj = settings_obj or OrganizationSettings.load()
    candidates = [
        getattr(django_settings, "SITE_BASE_URL", "") or "",
        settings_obj.website or "",
        (django_settings.CSRF_TRUSTED_ORIGINS or [""])[0],
    ]
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate:
            return candidate.rstrip("/")
    logger.warning(
        "No site base URL configured (SITE_BASE_URL / Organization Settings > Website "
        "/ CSRF_TRUSTED_ORIGINS). Scheduled phone blasts cannot register a Twilio "
        "status callback or absolute audio URL."
    )
    return None


# ffprobe format_name -> demuxer to force. Only plain audio/video containers;
# anything else (HLS/m3u8, concat, image2, ...) is refused, because those
# demuxers can make ffmpeg fetch URLs or read other local files.
_ALLOWED_AUDIO_FORMATS = {
    "mp3": "mp3",
    "wav": "wav",
    "ogg": "ogg",
    "flac": "flac",
    "aac": "aac",
    "matroska,webm": "matroska",
    "mov,mp4,m4a,3gp,3g2,mj2": "mov",
}


def _probe_audio_format(path):
    """Return the demuxer name to force for `path`, or raise AudioProcessingError."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-protocol_whitelist", "file",
                "-show_entries", "format=format_name",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True, timeout=30, check=True,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
        raise AudioProcessingError(
            "That audio file could not be processed. Please try a different recording."
        ) from exc
    format_name = (result.stdout or b"").decode("utf-8", "replace").strip()
    demuxer = _ALLOWED_AUDIO_FORMATS.get(format_name)
    if not demuxer:
        logger.warning("Rejected phone-blast upload with format %r", format_name)
        raise AudioProcessingError(
            "Please upload an MP3, WAV, M4A, OGG or WebM audio file."
        )
    return demuxer


def transcode_to_mp3(django_file) -> ContentFile:
    """Transcode an uploaded/recorded audio file to mono MP3 via ffmpeg.

    Browsers record WebM/Opus (Android/Chrome) or MP4/AAC (iOS Safari), neither
    of which Twilio's ``<Play>`` verb can fetch — it only plays MP3/WAV. We
    normalise every upload to MP3 so the stored file is always Twilio-playable.

    Returns a ``ContentFile`` named ``<uuid>.mp3``. Raises AudioProcessingError
    if ffmpeg is missing, errors, or times out.
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise AudioProcessingError(
            "Audio processing is unavailable (ffmpeg is not installed on the server)."
        )

    in_path = out_path = None
    try:
        suffix = os.path.splitext(getattr(django_file, "name", "") or "")[1] or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as in_tmp:
            for chunk in django_file.chunks():
                in_tmp.write(chunk)
            in_path = in_tmp.name
        out_path = os.path.join(
            tempfile.gettempdir(), f"anchorpoint-blast-{uuid.uuid4().hex}.mp3"
        )
        demuxer = _probe_audio_format(in_path)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-protocol_whitelist", "file",
                    "-f", demuxer, "-i", in_path,
                    "-ac", "1", "-codec:a", "libmp3lame", "-q:a", "5",
                    out_path,
                ],
                capture_output=True,
                timeout=60,
                check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise AudioProcessingError("Audio processing timed out.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", "replace")[-500:]
            logger.warning("ffmpeg failed transcoding audio: %s", detail)
            raise AudioProcessingError(
                "That audio file could not be processed. Please try a different recording."
            ) from exc

        with open(out_path, "rb") as result:
            data = result.read()
        if not data:
            raise AudioProcessingError("Transcoded audio was empty.")
        return ContentFile(data, name=f"{uuid.uuid4().hex}.mp3")
    finally:
        for path in (in_path, out_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
