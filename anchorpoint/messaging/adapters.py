"""Channel adapters: the seam between the outbound communications module and a provider.

Every adapter is built with the organization settings and offers two things:

- ``ready()``: is this channel configured well enough to send?
- ``send(delivery)``: send one Delivery; return the provider's id, or raise DeliveryError.

``settings.OUTBOUND_ADAPTERS`` maps each channel to an adapter class. Tests map every
channel to ``FakeAdapter``, so no test can reach Twilio by accident.
"""
import logging

from core.models import OrganizationSettings

from .services import get_site_base_url
from .twilio_client import (
    TwilioClient,
    TwilioConfigurationError,
    TwilioRequestError,
    twilio_configured,
)

logger = logging.getLogger(__name__)

CALL_STATUS_WEBHOOK_PATH = "/communications/phone-blast/webhook/call-status/"


class DeliveryError(Exception):
    """One Delivery could not be sent. The message is shown to staff."""


class TwilioSms:
    def __init__(self, settings_obj: OrganizationSettings):
        self.settings_obj = settings_obj

    def ready(self) -> bool:
        return twilio_configured(self.settings_obj)

    def send(self, delivery) -> str:
        try:
            client = TwilioClient(self.settings_obj)
            return client.send_sms(delivery.address, delivery.communication.body)
        except (TwilioConfigurationError, TwilioRequestError) as exc:
            raise DeliveryError(str(exc)) from exc


class TwilioVoice:
    """Plays the Communication's audio file. Twilio fetches it, so it needs an absolute URL."""

    def __init__(self, settings_obj: OrganizationSettings):
        self.settings_obj = settings_obj
        self.base_url = get_site_base_url(settings_obj)

    def ready(self) -> bool:
        return twilio_configured(self.settings_obj)

    def send(self, delivery) -> str:
        audio = delivery.communication.audio_file
        if not audio:
            raise DeliveryError("Upload an audio file before sending this blast.")
        if self.base_url:
            audio_url = f"{self.base_url}{audio.url}"
            callback_url = f"{self.base_url}{CALL_STATUS_WEBHOOK_PATH}"
        else:
            # Twilio can't fetch a relative URL; the call will likely fail, and with
            # no callback it can never settle. get_site_base_url already warned.
            audio_url, callback_url = audio.url, None
        try:
            client = TwilioClient(self.settings_obj)
            return client.initiate_call(
                delivery.address, audio_url, status_callback_url=callback_url
            )
        except (TwilioConfigurationError, TwilioRequestError) as exc:
            raise DeliveryError(str(exc)) from exc


class FakeAdapter:
    """In-memory adapter for tests: records every send, can be made unready or failing.

    State is class-level so a test can inspect it after the module builds its own
    instance; call ``FakeAdapter.reset()`` in setUp.
    """

    sent = []  # list of (channel, address, communication_id)
    is_ready = True
    fail_with = None  # str -> every send raises DeliveryError(fail_with)
    _counter = 0

    def __init__(self, settings_obj: OrganizationSettings):
        self.settings_obj = settings_obj

    @classmethod
    def reset(cls):
        cls.sent = []
        cls.is_ready = True
        cls.fail_with = None
        cls._counter = 0

    def ready(self) -> bool:
        return type(self).is_ready

    def send(self, delivery) -> str:
        cls = type(self)
        if cls.fail_with:
            raise DeliveryError(cls.fail_with)
        cls._counter += 1
        comm = delivery.communication
        cls.sent.append((comm.channel, delivery.address, comm.pk))
        return f"FAKE{cls._counter}"
