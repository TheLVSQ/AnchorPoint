"""
Print Service

Connection/health helper for an optional server-reachable printer (test prints
and availability checks from the admin UI).

Check-in labels are NOT printed here: they print from the kiosk's own browser
via CSS @media print (see checkin/kiosk/confirmation.html), because the printer
lives on the kiosk's local network and the remote app server cannot reach it.
"""

import logging

from django.utils import timezone

from ..models import PrinterConfiguration
from .printers import ESCPOSAdapter, CUPSAdapter

logger = logging.getLogger(__name__)


def get_printer_adapter(config: PrinterConfiguration):
    """Return the printer adapter for a given configuration."""
    adapters = {
        "escpos": ESCPOSAdapter,
        "cups": CUPSAdapter,
    }
    adapter_class = adapters.get(config.printer_type)
    if not adapter_class:
        raise ValueError(f"Unknown printer type: {config.printer_type}")
    connection_string = config.host or ""
    if config.printer_type == "escpos" and config.host:
        if not (
            config.host.startswith("tcp://")
            or config.host.startswith("usb://")
            or config.host.startswith("serial://")
            or config.host.startswith("file://")
        ):
            port = config.port or 9100
            connection_string = f"tcp://{config.host}:{port}"
    return adapter_class(connection_string)


class PrintService:
    """Connects to a thermal printer for test prints and label printing."""

    def __init__(self, printer_config: PrinterConfiguration = None):
        if printer_config is None:
            printer_config = (
                PrinterConfiguration.objects.filter(is_active=True, is_default=True).first()
                or PrinterConfiguration.objects.filter(is_active=True).first()
            )
        self.printer_config = printer_config
        self._adapter = None

    @property
    def adapter(self):
        if self._adapter is None and self.printer_config:
            self._adapter = get_printer_adapter(self.printer_config)
        return self._adapter

    def _mark_success(self):
        if not self.printer_config:
            return
        self.printer_config.last_successful_print_at = timezone.now()
        self.printer_config.save(update_fields=["last_successful_print_at"])

    def test_printer(self) -> bool:
        if not self.adapter:
            logger.error("No printer configured")
            return False
        printed = self.adapter.test_print()
        if printed:
            self._mark_success()
        return printed

    def is_printer_available(self) -> bool:
        if not self.adapter:
            return False
        return self.adapter.is_available()
