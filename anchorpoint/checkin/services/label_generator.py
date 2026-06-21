"""
Label Generator

Generates PIL images for thermal printer labels at 898px wide (76mm at 300 DPI)
× 600px tall (~51mm) — a printer-agnostic 3"x2" landscape design. It prints
full-width on a 76mm die-cut label (e.g. Zebra ZD500) and, rotated 90° by the
print queue, fits within a 62mm continuous roll (Brother QL) as a 51x76mm
portrait. Rotation is per-agent (PrintAgent.label_rotation); the artwork itself
is always rendered landscape.

- Child label: one per checked-in child
- Pickup tag: one per check-in group, parent carries this
"""

import logging

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

LABEL_WIDTH = 898    # 76mm at 300 DPI — 3"x2" landscape, the canonical design
CHILD_HEIGHT = 600   # ~51mm
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


def _text_height(draw, text, font) -> float:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]


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


def _centered_line(draw, text, font, y, fill="black", gap=10):
    """Draw centered text at y; return the y just below it (for stacking)."""
    _centered(draw, text, font, y, fill=fill)
    return y + _text_height(draw, text, font) + gap


def _draw_custody_shield(draw, cx, top, height=64, fill="#b91c1c"):
    """Draw a filled shield with a white '!' at center-x `cx`. Drawn (not a
    glyph) so it renders on any printer regardless of available fonts."""
    w = height * 0.82
    half = w / 2
    pts = [
        (cx - half, top),
        (cx + half, top),
        (cx + half, top + height * 0.52),
        (cx, top + height),
        (cx - half, top + height * 0.52),
    ]
    draw.polygon(pts, fill=fill)
    bang = _font(FONT_BOLD, int(height * 0.6))
    bw = _text_width(draw, "!", bang)
    bh = _text_height(draw, "!", bang)
    draw.text((cx - bw / 2, top + height * 0.16 - 2), "!", fill="white", font=bang)


def _guardian_phone(person):
    """Best guardian phone for a (minor) person: the household's primary adult,
    else the first adult member. Empty string if none."""
    household = person.households.all().first()
    if household is None:
        return ""
    adult = household.primary_adult
    if adult is None or not adult.phone:
        membership = (
            household.memberships.filter(relationship_type="adult")
            .select_related("person")
            .first()
        )
        adult = membership.person if membership else None
    return (adult.phone if adult and adult.phone else "") or ""


def _make_child_label(checkin, session) -> Image.Image:
    """Generate a child check-in label as a PIL Image.

    Layout (top→bottom, vertically stacked): first name (large), last name +
    grade, room with allergy(✚)/custody(shield) marks, allergy text, security
    code (large), optional emergency phone (VBS), session/date footer.
    """
    person = checkin.person
    img = Image.new("RGB", (LABEL_WIDTH, CHILD_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    usable = LABEL_WIDTH - 2 * MARGIN

    first = person.first_name
    last = person.last_name
    room = checkin.room.name if checkin.room else "—"
    code = checkin.security_code
    has_allergy = bool(person.allergies)
    has_custody = bool(person.custody_flag or person.custody_notes)

    # First name — large; last name (+ grade) beneath.
    y = _centered_line(draw, first, _fit_font(draw, first, FONT_BOLD, usable, 124, 56), 8, gap=16)
    grade = person.get_grade_display() if person.grade else ""
    last_line = f"{last}   ·   {grade}" if grade else last
    y = _centered_line(draw, last_line, _fit_font(draw, last_line, FONT_BOLD, usable, 64, 30), y, gap=10)

    # Room, with allergy ✚ and a drawn custody shield beside it.
    room_font = _fit_font(draw, room, FONT_BOLD, usable - 160, 56, 30)
    allergy_mark = "✚  " if has_allergy else ""
    room_text = f"{allergy_mark}{room}"
    rh = _text_height(draw, room_text, room_font)
    shield_w = (rh * 0.82 + 18) if has_custody else 0
    block_w = _text_width(draw, room_text, room_font) + shield_w
    x = (LABEL_WIDTH - block_w) / 2
    if allergy_mark:
        aw = _text_width(draw, allergy_mark, room_font)
        draw.text((x, y), allergy_mark, fill="#b91c1c", font=room_font)
        draw.text((x + aw, y), room, fill="black", font=room_font)
    else:
        draw.text((x, y), room, fill="black", font=room_font)
    if has_custody:
        _draw_custody_shield(draw, x + block_w - shield_w / 2 - 4, y, height=rh)
    y += rh + 12

    # Allergy detail text (red) — only when present.
    if has_allergy:
        allergy_text = f"Allergy: {person.allergies}".replace("\n", " ")
        y = _centered_line(
            draw, allergy_text, _fit_font(draw, allergy_text, FONT_BOLD, usable, 40, 22),
            y, fill="#b91c1c", gap=12,
        )

    # No-photo badge — only when consent is explicitly denied.
    if person.photo_consent == "denied":
        y = _centered_line(draw, "⊘ DO NOT PHOTOGRAPH",
                           _fit_font(draw, "⊘ DO NOT PHOTOGRAPH", FONT_BOLD, usable, 38, 22),
                           y, fill="#b91c1c", gap=12)

    # Security code — large.
    y = _centered_line(draw, code, _fit_font(draw, code, FONT_BOLD, usable, 104, 56), y + 4, gap=8)

    # Emergency phone — minors only, and only when the session opts in (VBS).
    if session and getattr(session, "print_emergency_phone", False) and person.is_minor:
        phone = _guardian_phone(person)
        if phone:
            _centered_line(draw, f"Call: {phone}", _fit_font(draw, phone, FONT_BOLD, usable, 40, 24), y, gap=6)

    # Session / date — fixed footer.
    if session:
        session_line = f"{session.name}  ·  {session.date.strftime('%b')} {session.date.day}"
        meta_font = _fit_font(draw, session_line, FONT_BOLD, usable, 34, 22)
        _centered(draw, session_line, meta_font, CHILD_HEIGHT - 44, fill="black")

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
