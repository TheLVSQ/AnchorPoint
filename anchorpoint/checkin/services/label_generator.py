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
    """Draw a filled shield icon (FontAwesome-style) centred at x=cx, starting at
    y=top. Drawn (not a glyph) so it renders on any printer. Used as a discreet,
    text-free custody marker — the shield alone, no '!' and no label, so the
    concern isn't spelled out on the child's tag."""
    w = height * 0.82
    half = w / 2
    pts = [
        (cx, top),                          # top-centre peak
        (cx - half, top + height * 0.20),   # left shoulder
        (cx - half, top + height * 0.52),   # left side
        (cx, top + height),                 # bottom point
        (cx + half, top + height * 0.52),   # right side
        (cx + half, top + height * 0.20),   # right shoulder
    ]
    draw.polygon(pts, fill=fill)


def _draw_no_photo(draw, cx, cy, size, fill="#b91c1c"):
    """Draw a 'no photography' icon — a circle with a diagonal slash — centred at
    (cx, cy). Drawn (not a glyph) so it renders on any printer regardless of
    available fonts."""
    r = size / 2
    w = max(3, int(size * 0.09))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fill, width=w)
    off = r * 0.7071  # 45° slash from corner to corner of the circle
    draw.line([cx - off, cy + off, cx + off, cy - off], fill=fill, width=w)


def _guardian_phone(person):
    """Best guardian phone for a (minor) person: the household's primary adult,
    else the first adult member. Empty string if none."""
    household = person.primary_household
    if household is None:
        return ""
    adult = household.primary_adult
    if adult is None or not adult.phone:
        membership = (
            household.memberships.filter(relationship_type="adult")
            .select_related("person")
            .order_by("person__id")
            .first()
        )
        adult = membership.person if membership else None
    return (adult.phone if adult and adult.phone else "") or ""


def _emergency_contact(person):
    """(name, phone) to print on the label: the person's explicitly-set emergency
    contact when a phone is on record, otherwise the household guardian's phone as
    a fallback (name blank). The explicit contact can be anyone — e.g. a family
    friend named on a registration form, not necessarily a household member."""
    if getattr(person, "emergency_contact_phone", ""):
        return (person.emergency_contact_name or ""), person.emergency_contact_phone
    return "", _guardian_phone(person)


def _markers_render(draw, usable, has_custody, no_photo):
    """Return a render(y, band) that draws a centred strip of warning markers:
    a discreet custody shield (icon only — no text, so the concern isn't spelled
    out) and/or a 'do not photograph' icon with a label. Sized to the band
    height and shrunk to fit the usable width."""
    badges = []
    if has_custody:
        badges.append(("shield", ""))               # custody: icon only, kept discreet
    if no_photo:
        badges.append(("nophoto", "DO NOT PHOTOGRAPH"))

    def render(y, band):
        if not badges:
            return
        color = "#b91c1c"
        icon = min(band * 0.66, 56)
        pad = icon * 0.28        # gap between an icon and its label
        between = icon * 0.9     # gap between badges

        def label_width(font, label):
            return (pad + _text_width(draw, label, font)) if label else 0

        # Shrink one shared label font until the whole strip fits the width.
        size = int(min(band * 0.52, 42))
        while size > 14:
            font = _font(FONT_BOLD, size)
            total = sum(icon + label_width(font, lbl) for _, lbl in badges)
            total += between * (len(badges) - 1)
            if total <= usable:
                break
            size -= 2
        font = _font(FONT_BOLD, size)
        widths = [icon + label_width(font, lbl) for _, lbl in badges]
        total = sum(widths) + between * (len(badges) - 1)
        x = (LABEL_WIDTH - total) / 2
        cy = y + band / 2
        for (kind, label), w in zip(badges, widths):
            if kind == "shield":
                _draw_custody_shield(draw, x + icon / 2, cy - icon / 2, height=icon, fill=color)
            else:
                _draw_no_photo(draw, x + icon / 2, cy, icon, fill=color)
            if label:
                lh = _text_height(draw, label, font)
                draw.text((x + icon + pad, cy - lh / 2), label, fill=color, font=font)
            x += w + between

    return render


def _make_child_label(checkin, session) -> Image.Image:
    """Generate a child check-in label as a PIL Image.

    Top-to-bottom: full name (hero), age · grade, the check-in name, the
    security code (kept smaller than the name), room · date, then a bottom
    safety strip — emergency phone, allergy description, and custody / no-photo
    symbols. Rows are weighted horizontal bands spanning the full height and
    fonts auto-fit, so the label fills the space and never overlaps regardless
    of which optional rows are present.
    """
    person = checkin.person
    img = Image.new("RGB", (LABEL_WIDTH, CHILD_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    usable = LABEL_WIDTH - 2 * MARGIN

    room = checkin.room.name if checkin.room else "—"
    code = checkin.security_code
    has_allergy = bool(person.allergies)
    has_custody = bool(person.custody_flag or person.custody_notes)
    no_photo = person.photo_consent == "denied"

    rows = []  # each: (weight, render(band_top, band_height))

    def text_row(text, weight, fill="black"):
        def render(y, band, text=text, fill=fill):
            font = _fit_both(draw, text, FONT_BOLD, usable, band * 0.80)
            h = _text_height(draw, text, font)
            _centered(draw, text, font, y + (band - h) / 2, fill=fill)
        return (weight, render)

    # 1. Full name — the hero line.
    rows.append(text_row(f"{person.first_name} {person.last_name}".strip(), 2.4))

    # 2. Age · Grade.
    age_grade = []
    if person.age is not None:
        age_grade.append(f"Age {person.age}")
    if person.grade:
        age_grade.append(person.get_grade_display())
    if age_grade:
        rows.append(text_row("   ·   ".join(age_grade), 0.85))

    # 3. Check-in name (e.g. "VBS Check-In").
    if session and session.name:
        rows.append(text_row(session.name, 0.95))

    # 4. Security code — smaller than the name.
    rows.append(text_row(code, 1.4))

    # 5. Room · Date.
    room_line = [room]
    if session:
        room_line.append(f"{session.date.strftime('%b')} {session.date.day}")
    rows.append(text_row("   ·   ".join(room_line), 1.0))

    # 6. Bottom safety strip: emergency phone, allergy text, custody/no-photo symbols.
    # Print the guardian's number on kids' labels when the session opts in. Gate on
    # "is_minor is not False" rather than "is_minor" so children whose birthdate
    # isn't on file (is_minor is None — common for imported rosters like VBS) still
    # get it; only confirmed adults are skipped.
    if session and getattr(session, "print_emergency_phone", False) and person.is_minor is not False:
        name, phone = _emergency_contact(person)
        if phone:
            text = f"Call: {name} · {phone}" if name else f"Call: {phone}"
            rows.append(text_row(text, 0.6))

    if has_allergy:
        rows.append(text_row(f"✚ {person.allergies}".replace("\n", " "), 0.85, fill="#b91c1c"))

    if has_custody or no_photo:
        rows.append((0.95, _markers_render(draw, usable, has_custody, no_photo)))

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
