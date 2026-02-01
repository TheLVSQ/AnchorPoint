import base64
import json
import logging
from typing import Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from django.utils import timezone

from core.models import OrganizationSettings

from .models import (
    CommunicationLog,
    PhoneBlast,
    PhoneCall,
    SmsMessage,
    SmsRecipient,
)


logger = logging.getLogger(__name__)


class TwilioConfigurationError(Exception):
    """Raised when the organization has not configured Twilio credentials."""


class TwilioRequestError(Exception):
    """Raised when Twilio rejects an API request."""


def is_within_blackout_window(
    settings_obj: OrganizationSettings, moment
) -> bool:  # pragma: no cover - exercised via form tests
    if not settings_obj.sms_blackout_start or not settings_obj.sms_blackout_end:
        return False
    start = settings_obj.sms_blackout_start
    end = settings_obj.sms_blackout_end
    if start == end:
        return False
    local_moment = timezone.localtime(moment)
    now_time = local_moment.time()
    if start < end:
        return start <= now_time < end
    return now_time >= start or now_time < end


class TwilioService:
    SMS_ENDPOINT = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    CALLS_ENDPOINT = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"

    def __init__(self, settings_obj: OrganizationSettings):
        self.account_sid = (settings_obj.twilio_account_sid or "").strip()
        self.auth_token = (settings_obj.twilio_auth_token or "").strip()
        self.from_number = (settings_obj.twilio_phone_number or "").strip()
        if not all([self.account_sid, self.auth_token, self.from_number]):
            raise TwilioConfigurationError(
                "Add your Twilio SID, auth token, and phone number in Organization Settings."
            )

    def send_sms(self, to_number: str, body: str) -> str:
        payload = {
            "To": to_number,
            "From": self.from_number,
            "Body": body,
        }
        response = self._post(
            self.SMS_ENDPOINT.format(sid=self.account_sid),
            data=payload,
        )
        return response.get("sid", "")

    def initiate_call(self, to_number: str, audio_url: str) -> str:
        twiml = f"<Response><Play>{audio_url}</Play></Response>"
        payload = {
            "To": to_number,
            "From": self.from_number,
            "Twiml": twiml,
        }
        response = self._post(
            self.CALLS_ENDPOINT.format(sid=self.account_sid),
            data=payload,
        )
        return response.get("sid", "")

    def _post(self, url: str, data: dict) -> dict:
        encoded = urllib_parse.urlencode(data).encode("utf-8")
        request = urllib_request.Request(url, data=encoded)
        auth_bytes = f"{self.account_sid}:{self.auth_token}".encode("utf-8")
        request.add_header(
            "Authorization",
            f"Basic {base64.b64encode(auth_bytes).decode('ascii')}",
        )
        request.add_header(
            "Content-Type",
            "application/x-www-form-urlencoded",
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                payload = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            logger.exception("Twilio HTTP error: %s", detail or exc)
            raise TwilioRequestError(detail or str(exc)) from exc
        except urllib_error.URLError as exc:
            logger.exception("Twilio network error: %s", exc)
            raise TwilioRequestError(str(exc)) from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}


def deliver_sms_message(
    message: SmsMessage,
    *,
    settings_obj: OrganizationSettings | None = None,
    service: TwilioService | None = None,
) -> Tuple[int, int]:
    settings_obj = settings_obj or OrganizationSettings.load()
    service = service or TwilioService(settings_obj)
    now = timezone.now()
    message.status = SmsMessage.Status.PROCESSING
    message.save(update_fields=["status"])
    success_count = 0
    failure_count = 0

    for recipient in message.recipients.select_related("person"):
        if recipient.status != SmsRecipient.Status.PENDING:
            continue
        try:
            sid = service.send_sms(recipient.phone_number, message.body)
        except (TwilioConfigurationError, TwilioRequestError) as exc:
            recipient.status = SmsRecipient.Status.FAILED
            recipient.error_message = str(exc)
            recipient.save(update_fields=["status", "error_message"])
            failure_count += 1
            continue

        recipient.status = SmsRecipient.Status.SENT
        recipient.sent_at = timezone.now()
        recipient.twilio_sid = sid
        recipient.save(update_fields=["status", "sent_at", "twilio_sid"])
        success_count += 1

        if recipient.person:
            CommunicationLog.objects.create(
                person=recipient.person,
                communication_type=CommunicationLog.CommunicationType.SMS,
                summary=f"SMS sent by {message.created_by.get_full_name() or message.created_by.username}",
                detail=message.body,
                metadata={
                    "phone_number": recipient.phone_number,
                    "twilio_sid": sid,
                },
                recorded_by=message.created_by,
                sms_message=message,
            )

    if success_count:
        message.sent_at = now
    message.status = (
        SmsMessage.Status.COMPLETED if success_count else SmsMessage.Status.FAILED
    )
    message.save(update_fields=["status", "sent_at"])
    return success_count, failure_count


def deliver_phone_blast(
    blast: PhoneBlast,
    *,
    settings_obj: OrganizationSettings | None = None,
    service: TwilioService | None = None,
    base_url: str | None = None,
) -> Tuple[int, int]:
    """
    Deliver a phone blast to all pending recipients.

    Args:
        blast: The PhoneBlast instance to deliver
        settings_obj: Organization settings (optional, will load if not provided)
        service: TwilioService instance (optional, will create if not provided)
        base_url: The public base URL for audio files (e.g., "https://app.example.com").
                  Required for Twilio to fetch audio files. If not provided, will attempt
                  to use the site URL from organization settings.
    """
    settings_obj = settings_obj or OrganizationSettings.load()
    service = service or TwilioService(settings_obj)
    if not blast.audio_file:
        raise TwilioRequestError("Upload an audio file before sending this blast.")

    blast.status = PhoneBlast.Status.PROCESSING
    blast.started_at = timezone.now()
    blast.save(update_fields=["status", "started_at"])

    # Build absolute URL for audio file - Twilio needs a public URL
    if base_url:
        audio_url = f"{base_url.rstrip('/')}{blast.audio_file.url}"
    elif settings_obj.website:
        # Fall back to organization website setting
        audio_url = f"{settings_obj.website.rstrip('/')}{blast.audio_file.url}"
    else:
        # Last resort - use relative URL (won't work with Twilio in production!)
        audio_url = blast.audio_file.url
        logger.warning(
            "Phone blast %s using relative audio URL - this may not work with Twilio. "
            "Set a base_url or configure Organization Settings > Website.",
            blast.pk,
        )
    success_count = 0
    failure_count = 0
    for call in blast.calls.select_related("person"):
        if call.status != PhoneCall.Status.PENDING:
            continue
        try:
            sid = service.initiate_call(call.phone_number, audio_url)
        except (TwilioConfigurationError, TwilioRequestError) as exc:
            call.status = PhoneCall.Status.FAILED
            call.error_message = str(exc)
            call.completed_at = timezone.now()
            call.save(update_fields=["status", "error_message", "completed_at"])
            failure_count += 1
            continue

        call.status = PhoneCall.Status.COMPLETED
        call.call_sid = sid
        call.started_at = timezone.now()
        call.completed_at = timezone.now()
        call.save(
            update_fields=[
                "status",
                "call_sid",
                "started_at",
                "completed_at",
            ]
        )
        success_count += 1

        if call.person:
            CommunicationLog.objects.create(
                person=call.person,
                communication_type=CommunicationLog.CommunicationType.PHONE,
                summary=f"Phone blast '{blast.title}'",
                detail="Automated call delivered via Twilio.",
                metadata={
                    "phone_number": call.phone_number,
                    "twilio_sid": sid,
                },
                recorded_by=blast.created_by,
                phone_blast=blast,
            )

    blast.completed_at = timezone.now() if success_count else None
    blast.status = (
        PhoneBlast.Status.COMPLETED if success_count else PhoneBlast.Status.FAILED
    )
    blast.save(update_fields=["status", "completed_at"])
    return success_count, failure_count
