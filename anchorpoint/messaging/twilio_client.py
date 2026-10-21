"""Thin HTTP client for Twilio's SMS and call APIs (no SDK dependency).

The outbound communications module reaches Twilio only through the adapters in
`messaging/adapters.py`; staff operational alerts (`households/family_flags.py`) use
this client directly.
"""
import base64
import json
import logging
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from core.models import OrganizationSettings

logger = logging.getLogger(__name__)


class TwilioConfigurationError(Exception):
    """Raised when the organization has not configured Twilio credentials."""


class TwilioRequestError(Exception):
    """Raised when Twilio rejects an API request."""


def twilio_configured(settings_obj: OrganizationSettings) -> bool:
    return all(
        (getattr(settings_obj, f) or "").strip()
        for f in ("twilio_account_sid", "twilio_auth_token", "twilio_phone_number")
    )


class TwilioClient:
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

    def initiate_call(self, to_number: str, audio_url: str, status_callback_url: str = None) -> str:
        twiml = f"<Response><Play>{audio_url}</Play></Response>"
        payload = {
            "To": to_number,
            "From": self.from_number,
            "Twiml": twiml,
        }
        if status_callback_url:
            payload["StatusCallback"] = status_callback_url
            payload["StatusCallbackMethod"] = "POST"
            payload["StatusCallbackEvent"] = "completed"
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
