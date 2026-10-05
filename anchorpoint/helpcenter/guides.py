"""Help guide registry + Markdown rendering.

Guides are Markdown files in ``helpcenter/guides/``. To add one, drop the file
there and add a ``Guide`` to ``GUIDES`` — the /help/ list and page pick it up.

Images: write ``![Alt text](checkin-setup/01-dashboard.png)``; relative paths
resolve to ``helpcenter/static/help/<path>`` (served via ``{% static %}``, so
they're hashed in prod). ``tests.py`` checks every referenced image exists —
a missing one would 500 in prod under the hashed-manifest storage.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import markdown
from django.templatetags.static import static

GUIDES_DIR = Path(__file__).resolve().parent / "guides"


@dataclass(frozen=True)
class Guide:
    slug: str
    title: str
    summary: str
    audience: str

    @property
    def path(self):
        return GUIDES_DIR / f"{self.slug}.md"


GUIDES = [
    Guide(
        slug="checkin-setup",
        title="Setting up check-in",
        summary="Rooms, a check-in configuration, the kiosk PIN, the label printer, "
                "and a test run, start to finish.",
        audience="Check-in admins",
    ),
]

_BY_SLUG = {g.slug: g for g in GUIDES}

# src="..." on <img> tags that isn't absolute (http:, https:, /, data:).
_RELATIVE_IMG = re.compile(r'(<img\b[^>]*?\bsrc=")(?!https?:|/|data:)([^"]+)(")')


def get_guide(slug):
    return _BY_SLUG.get(slug)


def image_paths(text):
    """Relative image paths referenced by a guide's Markdown (for tests)."""
    return re.findall(r"!\[[^\]]*\]\((?!https?:|/|data:)([^)\s]+)", text)


def render_guide(guide):
    """Return (html, toc_tokens) for a guide. Cached per file mtime, so edits
    show up without a restart but prod renders each guide once."""
    return _render(guide.path, guide.path.stat().st_mtime)


@lru_cache(maxsize=32)
def _render(path, _mtime):
    md = markdown.Markdown(
        extensions=["extra", "toc", "admonition", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "2"}},
    )
    html = md.convert(path.read_text(encoding="utf-8"))
    # No loading="lazy": lazy images can come out blank in Print → Save as PDF.
    html = _RELATIVE_IMG.sub(
        lambda m: f'{m.group(1)}{static("help/" + m.group(2))}{m.group(3)}', html
    )
    return html, md.toc_tokens
