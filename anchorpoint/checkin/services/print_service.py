"""
Print Service

Connects to a configured thermal printer and prints check-in labels server-side.
"""

import logging
from io import BytesIO

from PIL import Image, ImageDraw
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

    def _render_label_png(self, lines: list[str], width_px=696, height_px=420) -> bytes:
        image = Image.new("RGB", (width_px, height_px), "white")
        draw = ImageDraw.Draw(image)
        y = 20
        for idx, line in enumerate(lines):
            draw.text((20, y), line, fill="black")
            y += 34 if idx == 0 else 28
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()

    def print_checkins(self, checkins, session) -> bool:
        """
        Print child labels plus one pickup label for a batch of check-ins.
        Returns True when all print jobs submit successfully.
        """
        if not self.adapter or not checkins:
            logger.warning("No printer configured or no check-ins to print")
            return False
        try:
            security_code = checkins[0].security_code
            success = True
            for checkin in checkins:
                room_name = checkin.room.name if checkin.room else "Unassigned"
                lines = [
                    f"{checkin.person.first_name} {checkin.person.last_name}",
                    f"{room_name}  Code: {checkin.security_code}",
                    f"{session.name}  {session.date:%b %d}",
                ]
                printed = self.adapter.print_image(self._render_label_png(lines))
                if printed:
                    checkin.child_label_printed = True
                    checkin.save(update_fields=["child_label_printed"])
                success = success and printed

            child_names = ", ".join([c.person.first_name for c in checkins])
            pickup_lines = [
                f"PICKUP CODE: {security_code}",
                child_names or "Child",
                f"{session.name}  {session.date:%b %d}",
            ]
            pickup_printed = self.adapter.print_image(self._render_label_png(pickup_lines))
            if pickup_printed:
                for checkin in checkins:
                    checkin.parent_label_printed = True
                    checkin.save(update_fields=["parent_label_printed"])
            all_sent = success and pickup_printed
            if all_sent:
                self._mark_success()
            return all_sent
        except Exception:
            logger.exception("Label print failed for check-in group")
            return False
