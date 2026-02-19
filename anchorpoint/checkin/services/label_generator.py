"""
Label Generator Service

Generates label images as PNG that can be printed on any thermal printer.
Uses Pillow (PIL) for universal compatibility.
"""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class LabelGenerator:
    """Generate label images that work with any thermal printer."""

    # Default DPI for thermal printers
    DEFAULT_DPI = 203

    # Font paths - these will be bundled with the app
    # Falls back to default font if custom fonts not available
    FONT_DIR = Path(__file__).parent.parent / "static" / "checkin" / "fonts"

    def __init__(self, width_mm=62, height_mm=29, dpi=None):
        """
        Initialize label generator with dimensions.

        Args:
            width_mm: Label width in millimeters
            height_mm: Label height in millimeters (None for auto-height)
            dpi: Printer DPI (default 203 for most thermal printers)
        """
        self.dpi = dpi or self.DEFAULT_DPI
        self.width_mm = width_mm
        self.height_mm = height_mm

        # Convert mm to pixels
        self.width_px = int(width_mm * self.dpi / 25.4)
        self.height_px = int(height_mm * self.dpi / 25.4) if height_mm else 200

        # Load fonts
        self._load_fonts()

    def _load_fonts(self):
        """Load fonts for label generation."""
        try:
            # Try to load custom fonts
            font_bold = self.FONT_DIR / "OpenSans-Bold.ttf"
            font_regular = self.FONT_DIR / "OpenSans-Regular.ttf"
            font_mono = self.FONT_DIR / "RobotoMono-Bold.ttf"

            if font_bold.exists():
                self.font_large = ImageFont.truetype(str(font_bold), 48)
                self.font_medium = ImageFont.truetype(str(font_regular), 24)
                self.font_small = ImageFont.truetype(str(font_regular), 18)
                self.font_code = ImageFont.truetype(str(font_mono), 36)
            else:
                # Fall back to default font
                self._use_default_fonts()
        except Exception:
            self._use_default_fonts()

    def _use_default_fonts(self):
        """Use PIL's default font as fallback."""
        # PIL's default font doesn't support sizing well, but it works
        default = ImageFont.load_default()
        self.font_large = default
        self.font_medium = default
        self.font_small = default
        self.font_code = default

    def _create_canvas(self):
        """Create a blank white canvas for the label."""
        # 1-bit image (black and white) is best for thermal printers
        return Image.new("1", (self.width_px, self.height_px), color=1)

    def _center_text(self, draw, text, y, font, fill=0):
        """Draw centered text on the canvas."""
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        x = (self.width_px - text_width) // 2
        draw.text((x, y), text, font=font, fill=fill)

    def generate_child_label(self, checkin) -> bytes:
        """
        Generate a child name tag as PNG.

        Args:
            checkin: CheckIn model instance

        Returns:
            PNG image as bytes
        """
        person = checkin.person
        img = self._create_canvas()
        draw = ImageDraw.Draw(img)

        # Child's name (large, centered)
        name = f"{person.first_name}"
        if person.last_name:
            name += f" {person.last_name[0]}."
        self._center_text(draw, name, 10, self.font_large)

        # Room assignment
        room_name = checkin.room.name if checkin.room else "Main Room"
        self._center_text(draw, room_name, 65, self.font_medium)

        # Security code (prominent)
        self._center_text(draw, checkin.security_code, 100, self.font_code)

        # Allergy indicator (if applicable)
        if person.allergies:
            # Draw a warning box in bottom left
            draw.rectangle([5, self.height_px - 25, 30, self.height_px - 5], fill=0)
            draw.text((12, self.height_px - 23), "!", font=self.font_small, fill=1)
            draw.text(
                (35, self.height_px - 22),
                "ALLERGY",
                font=self.font_small,
                fill=0,
            )

        # Service date in small text at bottom
        date_str = checkin.session.date.strftime("%m/%d/%Y")
        self._center_text(draw, date_str, self.height_px - 20, self.font_small)

        return self._to_bytes(img)

    def generate_parent_label(self, checkin, children_names=None) -> bytes:
        """
        Generate a parent claim tag as PNG.

        Args:
            checkin: CheckIn model instance (can be any child's checkin)
            children_names: List of children's names checked in with this code

        Returns:
            PNG image as bytes
        """
        img = self._create_canvas()
        draw = ImageDraw.Draw(img)

        # Header
        self._center_text(draw, "PARENT CLAIM TAG", 5, self.font_medium)

        # Security code (large and prominent)
        self._center_text(draw, checkin.security_code, 35, self.font_large)

        # Children's names
        if children_names:
            y = 90
            for name in children_names[:3]:  # Max 3 names to fit
                self._center_text(draw, name, y, self.font_small)
                y += 20

        # Instructions at bottom
        self._center_text(
            draw, "Present at pickup", self.height_px - 35, self.font_small
        )

        # Date
        date_str = checkin.session.date.strftime("%m/%d/%Y")
        self._center_text(draw, date_str, self.height_px - 18, self.font_small)

        return self._to_bytes(img)

    def generate_allergy_label(self, checkin) -> bytes:
        """
        Generate an allergy alert label as PNG.

        Args:
            checkin: CheckIn model instance

        Returns:
            PNG image as bytes
        """
        person = checkin.person
        img = self._create_canvas()
        draw = ImageDraw.Draw(img)

        # Warning header with inverted colors
        draw.rectangle([0, 0, self.width_px, 35], fill=0)
        self._center_text(draw, "⚠ ALLERGY ALERT ⚠", 8, self.font_medium)
        # Redraw in white on black background
        bbox = draw.textbbox((0, 0), "ALLERGY ALERT", font=self.font_medium)
        text_width = bbox[2] - bbox[0]
        x = (self.width_px - text_width) // 2
        draw.text((x, 8), "ALLERGY ALERT", font=self.font_medium, fill=1)

        # Child's name
        name = f"{person.first_name} {person.last_name}"
        self._center_text(draw, name, 45, self.font_medium)

        # Allergies (word wrap if needed)
        allergies = person.allergies or "See notes"
        # Simple word wrap
        if len(allergies) > 30:
            allergies = allergies[:27] + "..."
        self._center_text(draw, allergies, 75, self.font_medium)

        # Room
        room_name = checkin.room.name if checkin.room else ""
        if room_name:
            self._center_text(draw, f"Room: {room_name}", 105, self.font_small)

        # Security code
        self._center_text(draw, checkin.security_code, self.height_px - 20, self.font_code)

        return self._to_bytes(img)

    def generate_visitor_label(self, name, date=None) -> bytes:
        """
        Generate a visitor badge as PNG.

        Args:
            name: Visitor's name
            date: Date string (optional)

        Returns:
            PNG image as bytes
        """
        img = self._create_canvas()
        draw = ImageDraw.Draw(img)

        # Header
        self._center_text(draw, "VISITOR", 10, self.font_medium)

        # Name (large)
        self._center_text(draw, name, 45, self.font_large)

        # Date
        if date:
            self._center_text(draw, date, self.height_px - 20, self.font_small)

        return self._to_bytes(img)

    def _to_bytes(self, img) -> bytes:
        """Convert PIL Image to PNG bytes."""
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def preview_label(self, label_bytes) -> Image.Image:
        """
        Convert label bytes back to PIL Image for preview.

        Args:
            label_bytes: PNG bytes from generate_* methods

        Returns:
            PIL Image object
        """
        return Image.open(BytesIO(label_bytes))
