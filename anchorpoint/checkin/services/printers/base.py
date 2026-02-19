"""
Base Printer Adapter

Abstract base class for all printer adapters.
"""

from abc import ABC, abstractmethod
from io import BytesIO

from PIL import Image


class BasePrinterAdapter(ABC):
    """Base class for printer adapters."""

    def __init__(self, connection_string: str, **kwargs):
        """
        Initialize the printer adapter.

        Args:
            connection_string: Printer-specific connection string
            **kwargs: Additional printer-specific options
        """
        self.connection_string = connection_string
        self.options = kwargs

    @abstractmethod
    def print_image(self, image_bytes: bytes) -> bool:
        """
        Print a PNG image.

        Args:
            image_bytes: PNG image data as bytes

        Returns:
            True if print job was sent successfully
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the printer is available/connected.

        Returns:
            True if printer is available
        """
        pass

    def _bytes_to_image(self, image_bytes: bytes) -> Image.Image:
        """Convert PNG bytes to PIL Image."""
        return Image.open(BytesIO(image_bytes))

    def test_print(self) -> bool:
        """
        Print a test label to verify printer connection.

        Returns:
            True if test print was successful
        """
        # Create a simple test image
        img = Image.new("1", (400, 200), color=1)
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 390, 190], outline=0)
        draw.text((50, 80), "AnchorPoint Test Print", fill=0)

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        return self.print_image(buffer.getvalue())
