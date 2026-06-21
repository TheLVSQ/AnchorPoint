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


def _fit_both(draw, text, font_path, max_width, max_height, start_size=200, min_size=18):
    """Largest font that fits text within both a width and a height budget."""
    size = start_size
    font = _font(font_path, size)
    while size > min_size and (
        _text_width(draw, text, font) > max_width
        or _text_height(draw, text, font) > max_height
    ):
        size -= 4
        font = _font(font_path, size)
    return font


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

    The main rows (first name, last + grade, room with allergy/custody marks,
    optional allergy text / no-photo badge, security code, optional VBS phone)
    are spread evenly down the label so it fills the space; the session/date is
    a small fixed footer. Fonts auto-fit to width.
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

    # Rows are laid out in weighted horizontal bands spanning the full height,
    # so the label always fills the space and fonts shrink to fit when there are
    # more rows — never overlapping. Each row: (weight, render(band_top, band_h)).
    rows = []

    def text_row(text, weight, fill="black"):
        def render(y, band, text=text, fill=fill):
            font = _fit_both(draw, text, FONT_BOLD, usable, band * 0.80)
            h = _text_height(draw, text, font)
            _centered(draw, text, font, y + (band - h) / 2, fill=fill)
        return (weight, render)

    rows.append(text_row(first, 2.3))

    grade = person.get_grade_display() if person.grade else ""
    last_line = f"{last}   ·   {grade}" if grade else last
    rows.append(text_row(last_line, 1.1))

    # Room row: allergy ✚ + room + drawn custody shield, centered as a block.
    def render_room(y, band, room=room, a=has_allergy, c=has_custody):
        rf = _fit_both(draw, room, FONT_BOLD, usable - 180, band * 0.80)
        rh = _text_height(draw, room, rf)
        ty = y + (band - rh) / 2
        mark = "✚  " if a else ""
        text = f"{mark}{room}"
        shield_w = (rh * 0.82 + 18) if c else 0
        block_w = _text_width(draw, text, rf) + shield_w
        x = (LABEL_WIDTH - block_w) / 2
        if mark:
            aw = _text_width(draw, mark, rf)
            draw.text((x, ty), mark, fill="#b91c1c", font=rf)
            draw.text((x + aw, ty), room, fill="black", font=rf)
        else:
            draw.text((x, ty), room, fill="black", font=rf)
        if c:
            _draw_custody_shield(draw, x + block_w - shield_w / 2 - 4, ty, height=rh)

    rows.append((1.4, render_room))

    if has_allergy:
        rows.append(text_row(f"Allergy: {person.allergies}".replace("\n", " "), 1.0, fill="#b91c1c"))

    if person.photo_consent == "denied":
        rows.append(text_row("⊘ DO NOT PHOTOGRAPH", 1.0, fill="#b91c1c"))

    rows.append(text_row(code, 2.0))

    if session and getattr(session, "print_emergency_phone", False) and person.is_minor:
        phone = _guardian_phone(person)
        if phone:
            rows.append(text_row(f"Call: {phone}", 1.0))

    if session:
        session_line = f"{session.name}  ·  {session.date.strftime('%b')} {session.date.day}"
        rows.append(text_row(session_line, 0.85))

    total_h = CHILD_HEIGHT - 2 * MARGIN
    total_w = sum(w for w, _ in rows)
    y = MARGIN
    for weight, render in rows:
        band = total_h * weight / total_w
        render(y, band)
        y += band

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
