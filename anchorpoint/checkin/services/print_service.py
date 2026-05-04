"""
Print Service

Connects to a configured thermal printer for test prints and availability checks.
Label generation is handled by CSS @media print in the browser (kiosk confirmation page).
"""

import logging

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
    connection_string = f"{config.host}:{config.port}" if config.host else ""
    return adapter_class(connection_string)


class PrintService:
    """Connects to a thermal printer for test prints and availability checks."""

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

    def test_printer(self) -> bool:
        if not self.adapter:
            logger.error("No printer configured")
            return False
        return self.adapter.test_print()

    def is_printer_available(self) -> bool:
        if not self.adapter:
            return False
        return self.adapter.is_available()
