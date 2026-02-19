"""
ESC/POS Printer Adapter

Supports generic thermal receipt printers using ESC/POS commands.
Works with most cheap thermal printers including Chinese generics.

Requires: pip install python-escpos
"""

import logging

from .base import BasePrinterAdapter

logger = logging.getLogger(__name__)


class ESCPOSAdapter(BasePrinterAdapter):
    """
    Adapter for ESC/POS compatible thermal printers.

    Connection string formats:
    - USB: "usb://0x0416:0x5011" (vendor:product ID)
    - Network: "tcp://192.168.1.100:9100"
    - Serial: "serial:///dev/ttyUSB0:9600"
    - File/Device: "file:///dev/usb/lp0"
    """

    def __init__(self, connection_string: str, **kwargs):
        super().__init__(connection_string, **kwargs)
        self._printer = None

    def _get_printer(self):
        """Get or create printer connection."""
        if self._printer is not None:
            return self._printer

        try:
            from escpos import printer as escpos_printer
        except ImportError:
            raise ImportError(
                "python-escpos is required for ESC/POS printing. "
                "Install with: pip install python-escpos"
            )

        conn = self.connection_string

        if conn.startswith("tcp://"):
            # Network printer
            host_port = conn[6:]
            if ":" in host_port:
                host, port = host_port.rsplit(":", 1)
                port = int(port)
            else:
                host = host_port
                port = 9100
            self._printer = escpos_printer.Network(host, port)

        elif conn.startswith("usb://"):
            # USB printer by vendor:product ID
            ids = conn[6:]
            if ":" in ids:
                vendor, product = ids.split(":")
                vendor = int(vendor, 16) if vendor.startswith("0x") else int(vendor)
                product = int(product, 16) if product.startswith("0x") else int(product)
            else:
                raise ValueError(
                    "USB connection requires vendor:product format, e.g., usb://0x0416:0x5011"
                )
            self._printer = escpos_printer.Usb(vendor, product)

        elif conn.startswith("serial://"):
            # Serial port
            # Format: serial:///dev/ttyUSB0:9600
            parts = conn[9:].split(":")
            devfile = parts[0]
            baudrate = int(parts[1]) if len(parts) > 1 else 9600
            self._printer = escpos_printer.Serial(devfile, baudrate=baudrate)

        elif conn.startswith("file://"):
            # Direct file/device
            devfile = conn[7:]
            self._printer = escpos_printer.File(devfile)

        else:
            # Assume it's a file path
            self._printer = escpos_printer.File(conn)

        return self._printer

    def print_image(self, image_bytes: bytes) -> bool:
        """
        Print a PNG image using ESC/POS commands.

        Args:
            image_bytes: PNG image data

        Returns:
            True if successful
        """
        try:
            printer = self._get_printer()
            img = self._bytes_to_image(image_bytes)

            # Convert to mode suitable for thermal printing
            # ESC/POS works best with 1-bit images
            if img.mode != "1":
                img = img.convert("1")

            # Print the image
            printer.image(img)

            # Feed and cut (if supported)
            printer.ln(3)  # Feed 3 lines
            try:
                printer.cut()
            except Exception:
                # Not all printers support cut command
                pass

            return True

        except Exception as e:
            logger.error(f"ESC/POS print error: {e}")
            return False

    def is_available(self) -> bool:
        """Check if printer is available."""
        try:
            printer = self._get_printer()
            # Try to get printer status if supported
            return printer is not None
        except Exception as e:
            logger.warning(f"Printer not available: {e}")
            return False

    def close(self):
        """Close the printer connection."""
        if self._printer is not None:
            try:
                self._printer.close()
            except Exception:
                pass
            self._printer = None
