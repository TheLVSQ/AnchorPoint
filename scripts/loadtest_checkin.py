#!/usr/bin/env python3
"""VBS-scale load test for the check-in kiosk.

Drives the real HTTP flow a kiosk tablet uses — PIN unlock, quick-register a
new family, pick rooms, confirm — with N families across concurrent workers.
Works against a local stack or production (use --families small + --marker for
prod, and clean up afterwards).

Examples:
  # Heavy local run
  python3 scripts/loadtest_checkin.py --base-url http://localhost --pin 1234 \
      --families 50 --workers 12 --marker Loadtest

  # Production smoke (5 families, your phone, SMS opt-in)
  python3 scripts/loadtest_checkin.py --base-url https://anchorpoint.example \
      --pin 1234 --families 5 --workers 2 --marker SmokeTest \
      --parent-phone "+15551234567" --opt-in
"""

import argparse
import random
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests

FIRST_NAMES = [
    "Ava", "Ben", "Cora", "Dean", "Elle", "Finn", "Gemma", "Hank", "Iris",
    "Jude", "Kara", "Liam", "Mia", "Noah", "Opal", "Pete", "Quinn", "Rose",
]
SELECT_RE = re.compile(r'name="select_(\d+)"')
ROOM_RE = re.compile(r'name="room_\d+" value="(\d+)"')
CODE_RE = re.compile(r"letter-spacing:12px[^>]*>\s*([A-Z0-9]{4})\s*<")

results_lock = threading.Lock()


def _csrf(session, url):
    return {
        "csrfmiddlewaretoken": session.cookies.get("csrftoken", ""),
        # Django CSRF requires a same-origin referer over https
    }


def run_family(base, pin, index, marker, kids_count, parent_phone, opt_in, timings, errors):
    s = requests.Session()
    s.headers["Referer"] = base + "/"
    try:
        # 1. unlock
        t0 = time.time()
        r = s.get(f"{base}/checkin/kiosk/unlock/", timeout=30)
        r = s.post(f"{base}/checkin/kiosk/unlock/", data={"pin": pin, **_csrf(s, base)}, timeout=30)
        r.raise_for_status()
        # 2. lookup (binds today's check-in session to the kiosk cookie)
        r = s.get(f"{base}/checkin/kiosk/", timeout=30)
        r.raise_for_status()
        if "no_sessions" in r.text or "No check-in" in r.text:
            raise RuntimeError("no open check-in session")
        t_unlock = time.time() - t0

        # 3. quick-register a new family
        t0 = time.time()
        data = {
            "parent_first_name": f"Parent{index}",
            "parent_last_name": f"{marker}{index}",
            "parent_phone": parent_phone or f"+1555{1000000 + index}",
            "parent_email": "",
            "child_count": str(kids_count),
            **_csrf(s, base),
        }
        if opt_in:
            data["phone_opt_in"] = "on"
        for k in range(kids_count):
            years = random.randint(3, 11)
            bd = date.today() - timedelta(days=365 * years + 40)
            data[f"child_{k}-first_name"] = random.choice(FIRST_NAMES)
            data[f"child_{k}-last_name"] = ""
            data[f"child_{k}-birthdate"] = bd.isoformat()
            data[f"child_{k}-allergies"] = "Peanuts" if index % 4 == 0 and k == 0 else ""
        r = s.post(f"{base}/checkin/kiosk/register/", data=data, timeout=60)
        r.raise_for_status()
        if "/kiosk/family/" not in r.url:
            raise RuntimeError(f"register did not land on family select (url={r.url})")
        t_register = time.time() - t0

        # 4. select everyone + rooms
        t0 = time.time()
        person_ids = sorted(set(SELECT_RE.findall(r.text)))
        room_ids = sorted(set(ROOM_RE.findall(r.text)))
        if not person_ids:
            raise RuntimeError("no eligible members rendered")
        select_data = {**_csrf(s, base)}
        for i, pid in enumerate(person_ids):
            select_data[f"select_{pid}"] = "on"
            if room_ids:
                select_data[f"room_{pid}"] = room_ids[i % len(room_ids)]
        r = s.post(r.url, data=select_data, timeout=60)
        r.raise_for_status()
        if "/kiosk/confirmation/" not in r.url:
            raise RuntimeError(f"family select did not confirm (url={r.url})")
        m = CODE_RE.search(r.text)
        code = m.group(1) if m else None
        if not code:
            raise RuntimeError("no security code on confirmation page")
        t_checkin = time.time() - t0

        with results_lock:
            timings.append({
                "unlock": t_unlock, "register": t_register, "checkin": t_checkin,
                "total": t_unlock + t_register + t_checkin,
                "code": code, "kids": len(person_ids),
            })
        return True
    except Exception as exc:  # noqa: BLE001 - collect every failure mode
        with results_lock:
            errors.append(f"family {index}: {exc}")
        return False


def pct(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p / 100))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--pin", required=True)
    ap.add_argument("--families", type=int, default=20)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--marker", default="Loadtest")
    ap.add_argument("--parent-phone", default="")
    ap.add_argument("--opt-in", action="store_true")
    ap.add_argument("--max-kids", type=int, default=3)
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    timings, errors = [], []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(
                run_family, base, args.pin, i, args.marker,
                random.randint(1, args.max_kids), args.parent_phone, args.opt_in,
                timings, errors,
            )
            for i in range(1, args.families + 1)
        ]
        done = 0
        for f in as_completed(futures):
            done += 1
            if done % 10 == 0:
                print(f"  ...{done}/{args.families} families processed")
    wall = time.time() - started

    codes = [t["code"] for t in timings]
    kids = sum(t["kids"] for t in timings)
    print(f"\n=== RESULTS ({base}) ===")
    print(f"families ok/attempted: {len(timings)}/{args.families}   kids checked in: {kids}")
    print(f"wall time: {wall:.1f}s   throughput: {len(timings) / wall * 60:.1f} families/min")
    for step in ("unlock", "register", "checkin", "total"):
        vals = [t[step] for t in timings]
        if vals:
            print(f"{step:>9}: p50 {statistics.median(vals):.2f}s   p95 {pct(vals, 95):.2f}s   max {max(vals):.2f}s")
    dupes = len(codes) - len(set(codes))
    print(f"security codes: {len(codes)} issued, {len(set(codes))} unique"
          + (f"   *** {dupes} DUPLICATES ***" if dupes else "   (all unique)"))
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors[:10]:
            print(f"  - {e}")
    sys.exit(1 if (errors or dupes) else 0)


if __name__ == "__main__":
    main()
