#!/usr/bin/env python
"""Regenerate the screenshots used by the in-app Help guides (/help/).

Seeds a THROWAWAY database with fictional people (the repo is public — never
point this at real data), starts a dev server, and captures each screen with
your installed Google Chrome via Playwright. Optionally writes the guide as PDF.

One-time setup:
    docker run -d --name anchorpoint-docs-db -e POSTGRES_DB=anchorpoint_docs \\
      -e POSTGRES_USER=anchorpoint -e POSTGRES_PASSWORD=anchorpoint \\
      -p 127.0.0.1:5434:5432 postgres:16-alpine
    uv pip install --python .venv/bin/python playwright   # docs-only, not in requirements

Run from the repo root:
    DB_NAME=anchorpoint_docs DB_PORT=5434 .venv/bin/python scripts/help_screenshots.py \\
      [--pdf checkin-setup-guide.pdf]

On macOS, also set LABEL_FONT_DIR (see save_labels) or the sample labels are skipped.
"""

import argparse
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from datetime import date, time as dtime
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "anchorpoint"
OUT = APP / "helpcenter" / "static" / "help" / "checkin-setup"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
KIOSK = ".kiosk-header, .kiosk-card"
KIOSK_PIN = "2580"  # fictional, only exists in the throwaway docs DB

sys.path.insert(0, str(APP))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "anchorpoint.settings")
os.environ["DEBUG"] = "True"  # runserver serves static (incl. fresh screenshots)
SERVER_ENV = os.environ.copy()
# Playwright's sync API runs an event loop; this script's own ORM calls are fine.
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

if not os.environ.get("DB_NAME", "").endswith("_docs"):
    sys.exit("Refusing to run: set DB_NAME to a throwaway *_docs database (see docstring).")

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import Client  # noqa: E402
from django.utils import timezone  # noqa: E402

from checkin.models import (  # noqa: E402
    CheckInConfiguration, CheckInSession, CheckInWindow, PrintAgent, Room,
)
from core.models import OrganizationSettings  # noqa: E402
from households.models import Household, HouseholdMember  # noqa: E402
from people.models import Person  # noqa: E402


def years_ago(n, month=3, day=14):
    today = date.today()
    return date(today.year - n, month, day)


def seed():
    call_command("migrate", verbosity=0)
    call_command("createcachetable", verbosity=0)

    org = OrganizationSettings.load()
    org.name = "Harbor Community Church"
    org.kiosk_pin = KIOSK_PIN
    org.save()

    rooms = {}
    for order, (name, extra) in enumerate([
        ("Nursery", {"min_age": 0, "max_age": 1, "capacity": 8}),
        ("Toddlers", {"min_age": 2, "max_age": 3, "capacity": 10}),
        ("Preschool", {"min_age": 4, "max_age": 5, "min_grade": "pre-k", "max_grade": "pre-k", "capacity": 12}),
        ("Elementary", {"min_grade": "k", "max_grade": "5", "capacity": 30}),
    ]):
        rooms[name], _ = Room.objects.update_or_create(
            name=name, defaults={"building": "Children's Wing", "sort_order": order, **extra},
        )

    config, _ = CheckInConfiguration.objects.update_or_create(
        name="Sunday Kids",
        defaults={
            "location_name": "Children's Wing",
            "welcome_message": "Welcome to Harbor Kids! Search by last name or phone number.",
            "description": "Nursery through 5th grade, both Sunday services.",
            "max_age": 11, "min_grade": "pre-k", "max_grade": "5",
            "checkout_enabled": True,
        },
    )
    config.rooms.set(rooms.values())
    config.windows.filter(schedule_type=CheckInWindow.TYPE_SPECIFIC_DATE).delete()
    for opens, starts, closes, ends, notes in [
        (dtime(8, 30), dtime(9, 0), dtime(9, 30), dtime(10, 15), "First service"),
        (dtime(10, 15), dtime(10, 45), dtime(11, 15), dtime(12, 0), "Second service"),
    ]:
        CheckInWindow.objects.update_or_create(
            configuration=config, schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=0, checkin_opens=opens,
            defaults={"event_starts": starts, "checkin_closes": closes,
                      "event_ends": ends, "notes": notes},
        )

    families = [
        ("Carter", "555-201-4410", [
            ("Jordan", "adult", years_ago(38), "", ""),
            ("Sam", "adult", years_ago(36), "", ""),
            ("Ellie", "child", years_ago(7), "2", "Peanuts"),
            ("Theo", "child", years_ago(4), "pre-k", ""),
            ("Ruby", "child", years_ago(1), "", ""),
        ]),
        ("Nguyen", "555-201-7782", [
            ("Linh", "adult", years_ago(34), "", ""),
            ("Mai", "child", years_ago(9), "4", ""),
        ]),
        ("Okafor", "555-201-3307", [
            ("Grace", "adult", years_ago(41), "", ""),
            ("Daniel", "child", years_ago(10), "5", ""),
            ("Ada", "child", years_ago(3), "", "Dairy"),
        ]),
    ]
    for surname, phone, members in families:
        hh, _ = Household.objects.get_or_create(name=f"{surname} Family")
        for first, rel, born, grade, allergies in members:
            person, _ = Person.objects.update_or_create(
                first_name=first, last_name=surname,
                defaults={"birthdate": born, "grade": grade, "allergies": allergies,
                          "phone": phone if rel == "adult" else ""},
            )
            HouseholdMember.objects.get_or_create(
                household=hh, person=person, defaults={"relationship_type": rel},
            )

    front, _ = PrintAgent.objects.get_or_create(name="Front Desk Printer")
    front.token_hash = front.token_hash or secrets.token_hex(32)
    front.last_seen_at = timezone.now()
    front.label_width_mm, front.label_rotation = 62, 90
    front.hostname = front.local_ip = ""
    front.save()
    nursery, _ = PrintAgent.objects.get_or_create(name="Nursery Printer")
    nursery.token_hash = ""
    nursery.issue_pairing_code()
    nursery.save()

    user = User.objects.filter(username="docs-admin").first()
    if user is None:
        call_command("create_admin", username="docs-admin", email="docs@example.org",
                     name="Pat Rivera", stdout=StringIO())
        user = User.objects.get(username="docs-admin")
    return config, user


def start_server():
    proc = subprocess.Popen(
        [sys.executable, str(APP / "manage.py"), "runserver", f"127.0.0.1:{PORT}", "--noreload"],
        cwd=APP, env=SERVER_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/health/", timeout=1)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    sys.exit("Dev server didn't start:\n" + proc.stderr.read().decode())


def shoot(page, name, selector="#main", pad=0):
    """Screenshot one element, or with pad, the padded area spanning every
    element the selector matches (the kiosk's header + card, minus the blank
    full-height backdrop)."""
    path = OUT / f"{name}.png"
    if pad:
        boxes = [el.bounding_box() for el in page.locator(selector).all()]
        x0, y0 = min(b["x"] for b in boxes), min(b["y"] for b in boxes)
        x1 = max(b["x"] + b["width"] for b in boxes)
        y1 = max(b["y"] + b["height"] for b in boxes)
        page.screenshot(path=path, full_page=True, clip={
            "x": max(x0 - pad, 0), "y": max(y0 - pad, 0),
            "width": x1 - x0 + 2 * pad, "height": y1 - y0 + 2 * pad,
        })
    else:
        page.locator(selector).first.screenshot(path=path)
    print("  saved", path.relative_to(ROOT))


def save_labels(session):
    """Render a sample child label + pickup tag exactly as the printer gets them."""
    from checkin.services import label_generator as lg
    # Labels use Linux DejaVu fonts (present in the prod image). Off-Linux, point
    # LABEL_FONT_DIR at a folder holding DejaVuSans{,-Bold}.ttf (matplotlib ships
    # them in mpl-data/fonts/ttf) so the sample matches what the printer gets.
    font_dir = os.environ.get("LABEL_FONT_DIR")
    if font_dir:
        lg.FONT_BOLD = str(Path(font_dir) / "DejaVuSans-Bold.ttf")
        lg.FONT_REGULAR = str(Path(font_dir) / "DejaVuSans.ttf")
    if not Path(lg.FONT_BOLD).exists():
        print("  skipped sample labels: DejaVu fonts not found (set LABEL_FONT_DIR)")
        return
    _make_child_label, _make_pickup_tag = lg._make_child_label, lg._make_pickup_tag
    checkins = list(session.checkins.select_related("person", "room").order_by("person__birthdate"))
    if not checkins:
        return
    _make_child_label(checkins[0], session).save(OUT / "label-child.png")
    _make_pickup_tag(checkins, checkins[0].security_code, session).save(OUT / "label-pickup.png")
    print("  saved sample labels")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", help="Also save the guide as a PDF to this path.")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    config, user = seed()
    client = Client()
    client.force_login(user)
    cookie = {"name": "sessionid", "value": client.cookies["sessionid"].value,
              "domain": "127.0.0.1", "path": "/"}
    room = Room.objects.get(name="Preschool")

    server = start_server()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")

            # ---- Admin screens (desktop, signed in) ----
            admin = browser.new_context(viewport={"width": 1280, "height": 900},
                                        device_scale_factor=2, color_scheme="light")
            admin.add_cookies([cookie])
            page = admin.new_page()

            page.goto(f"{BASE}/checkin/rooms/")
            shoot(page, "01-rooms")
            page.goto(f"{BASE}/checkin/rooms/{room.pk}/edit/")
            shoot(page, "02-room-form")
            page.goto(f"{BASE}/checkin/configurations/")
            shoot(page, "03-configurations")
            page.goto(f"{BASE}/checkin/configurations/{config.pk}/")
            shoot(page, "04a-config-basics", selector=".detail-card >> nth=0")
            shoot(page, "04b-config-eligibility", selector=".detail-card >> nth=1")
            shoot(page, "04c-config-window", selector=".window-row")
            shoot(page, "04d-config-rooms", selector=".detail-card >> nth=3")
            page.goto(f"{BASE}/settings/organization/")
            shoot(page, "05-kiosk-pin", selector="#kiosk-pin")
            page.goto(f"{BASE}/checkin/agents/")
            shoot(page, "06-print-agents")

            # ---- Kiosk (iPad landscape, not signed in) ----
            # Open check-in now with a temporary today-only window around the
            # current time (sessions from earlier runs are cleared first).
            CheckInSession.objects.filter(configuration=config).delete()
            now = timezone.localtime()
            start = max(now.hour * 60 + now.minute - 20, 0) // 15 * 15
            at = lambda m: dtime(min(m, 1439) // 60, min(m, 1439) % 60)  # noqa: E731
            temp = CheckInWindow.objects.create(
                configuration=config, schedule_type=CheckInWindow.TYPE_SPECIFIC_DATE,
                specific_date=now.date(), checkin_opens=at(start), event_starts=at(start + 30),
                checkin_closes=at(start + 60), event_ends=at(start + 105),
            )
            kiosk = browser.new_context(viewport={"width": 1024, "height": 768},
                                        device_scale_factor=2, color_scheme="light")
            kp = kiosk.new_page()
            kp.goto(f"{BASE}/checkin/kiosk/")
            shoot(kp, "07-kiosk-unlock", selector=KIOSK, pad=32)
            kp.fill("input[name=pin]", KIOSK_PIN)
            kp.click("button[type=submit]")
            kp.wait_for_url("**/kiosk/")
            shoot(kp, "08-kiosk-search", selector=KIOSK, pad=32)
            kp.fill("input[name=query]", "Carter")
            kp.keyboard.press("Enter")
            kp.wait_for_load_state("networkidle")
            shoot(kp, "09-kiosk-results", selector=KIOSK, pad=32)
            kp.click("text=Carter Family")
            kp.wait_for_load_state("networkidle")
            for first in ("Ellie", "Theo"):
                person = Person.objects.get(first_name=first, last_name="Carter")
                kp.check(f"input[name=select_{person.pk}]", force=True)
            shoot(kp, "10-kiosk-family", selector=KIOSK, pad=32)
            kp.click("button[type=submit]")
            kp.wait_for_url("**/confirmation/**")
            shoot(kp, "11-kiosk-done", selector=KIOSK, pad=32)
            kiosk.close()

            session = CheckInSession.objects.filter(configuration=config).latest("created_at")
            save_labels(session)

            page.goto(f"{BASE}/checkin/")
            shoot(page, "00-dashboard")
            page.goto(f"{BASE}/checkin/sessions/{session.pk}/manager/")
            page.wait_for_load_state("networkidle")
            shoot(page, "12-manager")

            if args.pdf:
                page.goto(f"{BASE}/help/checkin-setup/")
                page.wait_for_load_state("networkidle")
                page.emulate_media(media="print")
                page.pdf(path=args.pdf, format="Letter", print_background=True,
                         margin={"top": "0.6in", "bottom": "0.6in", "left": "0.6in", "right": "0.6in"})
                print("  saved", args.pdf)

            temp.delete()
            admin.close()
            browser.close()
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
