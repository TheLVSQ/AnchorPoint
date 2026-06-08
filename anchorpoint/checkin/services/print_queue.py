"""Queue rendered labels for a local print agent (pull-based printing).

The server renders labels to PNG and stores them as PrintJob rows; an agent on
the LAN polls for them and prints. The server never talks to the printer.
"""

import io
import logging

from .label_generator import LabelGenerator, _font
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


def _png_bytes(image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
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
                image_data=_png_bytes(image),
                kind=kind,
                description=description,
            )
        )
    PrintJob.objects.bulk_create(jobs)
    logger.info("Queued %d label(s) for print agent '%s'", len(jobs), agent.name)
    return len(jobs)


def enqueue_test_label(agent) -> PrintJob:
    """Queue a simple test label (used by the Settings 'Test Print' button)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (696, 200), "white")
    draw = ImageDraw.Draw(img)
    draw.text(
        (24, 50),
        "AnchorPoint",
        fill="black",
        font=_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44),
    )
    draw.text(
        (24, 110),
        "Print agent test ✓",
        fill="#555555",
        font=_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28),
    )
    return PrintJob.objects.create(
        agent=agent,
        image_data=_png_bytes(img),
        kind="test",
        description="Test print",
    )
