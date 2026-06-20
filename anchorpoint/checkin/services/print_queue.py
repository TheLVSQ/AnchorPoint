"""Queue rendered labels for a local print agent (pull-based printing).

The server renders labels to PNG and stores them as PrintJob rows; an agent on
the LAN polls for them and prints. The server never talks to the printer.
"""

import io
import logging

from .label_generator import (
    CHILD_HEIGHT,
    FONT_BOLD,
    FONT_REGULAR,
    LABEL_WIDTH,
    LabelGenerator,
    _centered,
    _font,
)
from ..models import PrintAgent, PrintJob

logger = logging.getLogger(__name__)


def get_active_agent():
    """The agent that should receive jobs (Phase 1: the single active, paired
    agent — most-recently-seen wins). None if no paired agent exists."""
    return (
        PrintAgent.objects.filter(is_active=True)
        .exclude(token_hash="")
        .order_by("-last_seen_at")
        .first()
    )


def _png_bytes(image, rotation=0) -> bytes:
    # Artwork is rendered landscape (898px = 76mm wide); rotate per the agent's
    # label_rotation so a narrow continuous roll (e.g. 62mm Brother) gets the
    # design stood up, while a wide die-cut label (76mm Zebra) prints it as-is.
    if rotation:
        image = image.rotate(rotation, expand=True)
    buf = io.BytesIO()
    # Tag the PNG at 300dpi so printers/drivers interpret the physical size
    # correctly instead of assuming 72dpi.
    image.save(buf, format="PNG", dpi=(300, 300))
    return buf.getvalue()


def enqueue_checkin_labels(checkins, session) -> int:
    """Render labels for a check-in batch and queue them for the active agent.

    Returns the number of jobs queued (0 if no agent is available, which lets
    the kiosk fall back to browser printing).
    """
    agent = get_active_agent()
    if agent is None:
        return 0

    checkins = list(checkins)
    images = LabelGenerator.build_label_set(checkins, session)
    if not images:
        return 0

    # build_label_set returns one child label per check-in (in order), then a
    # single pickup tag as the final image.
    jobs = []
    for idx, image in enumerate(images):
        if idx == len(images) - 1:
            kind, description = "pickup", "Pickup tag"
        else:
            person = checkins[idx].person
            kind, description = "child", f"{person.first_name} {person.last_name}"
        jobs.append(
            PrintJob(
                agent=agent,
                image_data=_png_bytes(image, agent.label_rotation),
                kind=kind,
                description=description,
            )
        )
    PrintJob.objects.bulk_create(jobs)
    logger.info("Queued %d label(s) for print agent '%s'", len(jobs), agent.name)
    return len(jobs)


def enqueue_test_label(agent) -> PrintJob:
    """Queue a test label (Settings 'Test Print' button).

    Rendered at the same canonical landscape size as real labels so it rotates
    and scales identically — otherwise its aspect ratio prints with a long blank
    run on a rotated continuous roll.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (LABEL_WIDTH, CHILD_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    _centered(draw, "AnchorPoint", _font(FONT_BOLD, 110), 150)
    _centered(draw, "Print agent test", _font(FONT_REGULAR, 60), 320, fill="#333333")
    _centered(draw, "OK ✓", _font(FONT_BOLD, 90), 430)
    return PrintJob.objects.create(
        agent=agent,
        image_data=_png_bytes(img, agent.label_rotation),
        kind="test",
        description="Test print",
    )
