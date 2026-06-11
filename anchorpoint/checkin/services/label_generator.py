"""
Label Generator

Generates PIL images for thermal printer labels at 696px wide (62mm at 300 DPI),
sized for a 62mm continuous roll (Brother QL): each label is ~62x51mm so names
are readable at a glance from a lanyard or shirt sticker.

- Child label: one per checked-in child
- Pickup tag: one per check-in group, parent carries this
"""

import logging

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

LABEL_WIDTH = 696    # 62mm at 300 DPI — Brother QL required resolution
CHILD_HEIGHT = 600   # ~51mm cut length
PICKUP_HEIGHT = 600
MARGIN = 28

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(path: str, size: int) -> ImageFont.ImageFont:
    """Load a TrueType font, falling back to PIL default in dev/CI environments."""
    try:
        return ImageFont.truetype(path, size)
    except (IOError, OSError):
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    """Return pixel width of rendered text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _fit_font(draw, text, font_path, max_width, start_size, min_size=24):
    """Largest font (from start_size down) that renders text within max_width."""
    size = start_size
    font = _font(font_path, size)
    while size > min_size and _text_width(draw, text, font) > max_width:
        size -= 6
        font = _font(font_path, size)
    return font


def _centered(draw, text, font, y, fill="black"):
    draw.text(((LABEL_WIDTH - _text_width(draw, text, font)) / 2, y), text, fill=fill, font=font)


def _make_child_label(checkin, session) -> Image.Image:
    """Generate a child check-in label as a PIL Image."""
    img = Image.new("RGB", (LABEL_WIDTH, CHILD_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    usable = LABEL_WIDTH - 2 * MARGIN

    first = checkin.person.first_name
    last = checkin.person.last_name
    room = checkin.room.name if checkin.room else "—"
    code = checkin.security_code

    # First name — huge, centred; last name beneath it
    first_font = _fit_font(draw, first, FONT_BOLD, usable, 150, min_size=60)
    _centered(draw, first, first_font, 16)
    last_font = _fit_font(draw, last, FONT_BOLD, usable, 64, min_size=32)
    _centered(draw, last, last_font, 186, fill="black")

    # Room — centred, with alert icons (allergy ✚ / custody ⚠) beside it
    icons = []
    if checkin.person.allergies:
        icons.append("✚")
    if checkin.person.custody_flag:
        icons.append("⚠")
    room_line = room if not icons else f"{room}   {'  '.join(icons)}"
    room_font = _fit_font(draw, room_line, FONT_BOLD, usable, 54, min_size=30)
    room_w = _text_width(draw, room_line, room_font)
    room_x = (LABEL_WIDTH - room_w) / 2
    if icons:
        # Draw the room text and the red icon block separately so icons pop.
        plain = room + "   "
        draw.text((room_x, 280), plain, fill="black", font=room_font)
        draw.text(
            (room_x + _text_width(draw, plain, room_font), 280),
            "  ".join(icons),
            fill="#dc2626",
            font=room_font,
        )
    else:
        draw.text((room_x, 280), room_line, fill="black", font=room_font)

    # Security code — big, centred near the bottom
    code_font = _fit_font(draw, code, FONT_BOLD, usable, 120, min_size=60)
    _centered(draw, code, code_font, 380)

    # Session / date — bottom strip
    if session:
        session_line = f"{session.name}  ·  {session.date.strftime('%b')} {session.date.day}"
        meta_font = _fit_font(draw, session_line, FONT_BOLD, usable, 36, min_size=24)
        _centered(draw, session_line, meta_font, CHILD_HEIGHT - 72, fill="black")

    return img


def _make_pickup_tag(checkins, security_code: str, session) -> Image.Image:
    """Generate the parent pickup tag — one per check-in group."""
    img = Image.new("RGB", (LABEL_WIDTH, PICKUP_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    usable = LABEL_WIDTH - 2 * MARGIN

    header_font = _font(FONT_BOLD, 40)
    _centered(draw, "P I C K U P   T A G", header_font, 24, fill="black")

    # Security code — gigantic, centred
    code_font = _fit_font(draw, security_code, FONT_BOLD, usable, 230, min_size=90)
    _centered(draw, security_code, code_font, 90)

    # Children's first names — centred, below code
    names = "  ·  ".join(c.person.first_name for c in checkins)
    names_font = _fit_font(draw, names, FONT_BOLD, usable, 56, min_size=30)
    _centered(draw, names, names_font, 420, fill="black")

    # Session / date — centred, bottom
    if session:
        session_line = f"{session.name}  ·  {session.date.strftime('%b')} {session.date.day}"
        meta_font = _fit_font(draw, session_line, FONT_BOLD, usable, 36, min_size=24)
        _centered(draw, session_line, meta_font, PICKUP_HEIGHT - 72, fill="black")

    return img


class LabelGenerator:
    @staticmethod
    def build_label_set(checkins, session) -> list:
        """
        Returns a list of PIL Images:
          - One child label per check-in (in order)
          - One pickup tag (shared security code from the first check-in)
        Returns [] if checkins is empty.
        """
        checkins = list(checkins)
        if not checkins:
            return []

        security_code = checkins[0].security_code
        images = []
        for checkin in checkins:
            images.append(_make_child_label(checkin, session))
        images.append(_make_pickup_tag(checkins, security_code, session))
        return images
