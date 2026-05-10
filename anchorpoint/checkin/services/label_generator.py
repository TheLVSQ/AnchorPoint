"""
Label Generator

Generates PIL images for thermal printer labels at 696px wide (62mm at 300 DPI).

- Child label: one per checked-in child (~220px tall)
- Pickup tag: one per check-in group, parent carries this (~200px tall)
"""

import logging

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

LABEL_WIDTH = 696   # 62mm at 300 DPI — Brother QL required resolution
CHILD_HEIGHT = 220
PICKUP_HEIGHT = 200
MARGIN = 24

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


def _make_child_label(checkin, session) -> Image.Image:
    """Generate a child check-in label as a PIL Image."""
    img = Image.new("RGB", (LABEL_WIDTH, CHILD_HEIGHT), "white")
    draw = ImageDraw.Draw(img)

    name_font = _font(FONT_BOLD, 46)
    room_font = _font(FONT_REGULAR, 22)
    code_font = _font(FONT_BOLD, 44)
    meta_font = _font(FONT_REGULAR, 16)

    name = f"{checkin.person.first_name} {checkin.person.last_name}"
    room = checkin.room.name if checkin.room else "—"
    code = checkin.security_code

    # Name — left-aligned, top
    draw.text((MARGIN, 18), name, fill="black", font=name_font)

    # Security code — right-aligned, top
    code_w = _text_width(draw, code, code_font)
    draw.text((LABEL_WIDTH - MARGIN - code_w, 18), code, fill="black", font=code_font)

    # Room — left, second row
    draw.text((MARGIN, 82), room, fill="#555555", font=room_font)

    # Alert icons — right, second row (allergy = ✚ red, custody = ⚠)
    icons = []
    if checkin.person.allergies:
        icons.append("✚")
    if checkin.person.custody_flag:
        icons.append("⚠")
    if icons:
        icon_text = "  ".join(icons)
        icon_w = _text_width(draw, icon_text, room_font)
        draw.text(
            (LABEL_WIDTH - MARGIN - icon_w, 82),
            icon_text,
            fill="#dc2626",
            font=room_font,
        )

    # Separator line
    draw.line(
        [(MARGIN, CHILD_HEIGHT - 38), (LABEL_WIDTH - MARGIN, CHILD_HEIGHT - 38)],
        fill="#dddddd",
        width=1,
    )

    # Session / date — bottom strip
    if session:
        session_line = f"{session.name}  ·  {session.date.strftime('%b')} {session.date.day}"
    else:
        session_line = ""
    draw.text((MARGIN, CHILD_HEIGHT - 30), session_line, fill="#999999", font=meta_font)

    return img


def _make_pickup_tag(checkins, security_code: str, session) -> Image.Image:
    """Generate the parent pickup tag — one per check-in group."""
    img = Image.new("RGB", (LABEL_WIDTH, PICKUP_HEIGHT), "white")
    draw = ImageDraw.Draw(img)

    code_font = _font(FONT_BOLD, 88)
    names_font = _font(FONT_REGULAR, 22)
    meta_font = _font(FONT_REGULAR, 16)

    # Security code — large, centred
    code_w = _text_width(draw, security_code, code_font)
    draw.text(
        ((LABEL_WIDTH - code_w) / 2, 14),
        security_code,
        fill="black",
        font=code_font,
    )

    # Children's first names — centred, below code
    names = "  ·  ".join(c.person.first_name for c in checkins)
    names_w = _text_width(draw, names, names_font)
    draw.text(
        ((LABEL_WIDTH - names_w) / 2, 118),
        names,
        fill="#555555",
        font=names_font,
    )

    # Session / date — centred, bottom
    if session:
        session_line = f"{session.name}  ·  {session.date.strftime('%b')} {session.date.day}"
    else:
        session_line = ""
    session_w = _text_width(draw, session_line, meta_font)
    draw.text(
        ((LABEL_WIDTH - session_w) / 2, PICKUP_HEIGHT - 28),
        session_line,
        fill="#999999",
        font=meta_font,
    )

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
