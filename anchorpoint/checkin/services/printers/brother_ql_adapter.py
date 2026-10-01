"""
Brother QL Adapter

Sends PIL images to a Brother QL label printer via the brother_ql library.
Supports network (tcp://) and USB (usb:///dev/usb/lp0) connections.

Requires: brother_ql==0.11.0
"""

import logging
import socket

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# Lazy import — missing library logs a warning but doesn't break startup
try:
    from brother_ql.raster import BrotherQLRaster
    from brother_ql.conversion import convert
    from brother_ql.backends.helpers import send as ql_send
    BROTHER_QL_AVAILABLE = True
except ImportError:
    BROTHER_QL_AVAILABLE = False
    BrotherQLRaster = None
    convert = None
    ql_send = None


def _test_image() -> Image.Image:
    """Simple test-print image."""
    img = Image.new("RGB", (696, 100), "white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 30), "AnchorPoint — Test Print", fill="black")
    return img


class BrotherQLAdapter:
    """
    Sends label images to a Brother QL printer.

    connection_string:
      - Network: 'tcp://192.168.x.x' or 'tcp://192.168.x.x:9100'
      - USB:     'usb:///dev/usb/lp0'

    ql_model: Brother QL model string, e.g. 'QL-800'
    """

    def __init__(self, connection_string: str, ql_model: str = "QL-800"):
        self.connection_string = connection_string
        self.ql_model = ql_model

    def print_images(self, images: list) -> bool:
        """
        Convert PIL images to Brother QL raster and send to printer.
        Cuts between each label.
        """
        if not BROTHER_QL_AVAILABLE:
            logger.error("brother_ql library not installed — cannot print")
            return False
        try:
            qlr = BrotherQLRaster(self.ql_model)
            convert(qlr, images, "62", cut=True, rotate="0", dither=False, compress=False)
            backend = "network" if self.connection_string.startswith("tcp://") else "pyusb"
            ql_send(qlr.data, self.connection_string, backend_identifier=backend, blocking=True)
            return True
        except Exception:
            logger.exception("BrotherQL print failed")
            return False

    def is_available(self) -> bool:
        """Check network reachability; USB is assumed available."""
        if not self.connection_string.startswith("tcp://"):
            return True
        try:
            raw = self.connection_string.replace("tcp://", "")
            host, _, port_str = raw.partition(":")
            port = int(port_str) if port_str else 9100
            sock = socket.create_connection((host, port), timeout=2)
            sock.close()
            return True
        except Exception:
            return False

    def test_print(self) -> bool:
        """Print a test label to verify printer health."""
        return self.print_images([_test_image()])
