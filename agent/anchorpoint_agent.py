#!/usr/bin/env python3
"""
AnchorPoint print agent.

Runs next to a label printer (e.g. on a Raspberry Pi) and prints check-in tags.
It only makes OUTBOUND HTTPS calls to your AnchorPoint server — no inbound
networking, no VPN, no port forwarding.

Setup:
  1. In AnchorPoint: Settings -> Print Agents -> Add Agent, copy the pairing code.
  2. Pair this agent:
       python3 anchorpoint_agent.py pair --server https://your-anchorpoint-url --code ABCD1234
  3. Run it:
       python3 anchorpoint_agent.py run            # uses the system default printer
       python3 anchorpoint_agent.py run --printer Brother_QL_820NWB

Printing uses CUPS (`lp`), so install your printer in CUPS first (see
docs/checkin-printer-raspberry-pi.md). Requires Python 3 and `requests`.
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

import requests

CONFIG_PATH = os.environ.get(
    "ANCHORPOINT_AGENT_CONFIG",
    os.path.join(os.path.expanduser("~"), ".anchorpoint_agent.json"),
)
POLL_INTERVAL_SECONDS = 2
HTTP_TIMEOUT = 15

# After submitting a label we wait for it to actually finish printing before
# sending the next one. `lp` returns as soon as a job is QUEUED, so without this
# a multi-label batch (e.g. a family checking in several kids at once) fires
# several jobs in milliseconds and overruns a single-connection USB bridge like
# ipp-usb (Brother QL over USB), wedging the queue mid-batch. Serialising on
# physical completion keeps batches feeding one label at a time.
JOB_DONE_TIMEOUT_SECONDS = 45   # give up waiting after this so a stuck job can't hang the agent
JOB_POLL_SECONDS = 0.4          # how often to check whether the job has cleared the queue
JOB_SETTLE_SECONDS = 0.4        # brief pause after a label finishes, before the next one

# Self-heal after a failed print. A Brother QL over USB (ipp-usb) can wedge once
# the Pi has sat idle — USB autosuspend sleeps the printer and the bridge won't
# wake it, and CUPS often disables the queue after the resulting error — so the
# next check-in silently doesn't print until someone reboots the Pi. After a
# failure we clear the queue, bounce ipp-usb/cups, and re-enable the queue, so it
# recovers on its own. Best-effort + rate-limited; the service restarts need the
# small sudoers grant install.sh adds (without it the sudo call just no-ops).
# Set ANCHORPOINT_NO_RECOVER=1 to disable.
RECOVER_AFTER_FAILURE = os.environ.get("ANCHORPOINT_NO_RECOVER") != "1"
RECOVERY_COOLDOWN_SECONDS = 120   # don't bounce cups on every poll if a printer keeps failing
RECOVERY_SETTLE_SECONDS = 4       # give cups/ipp-usb a moment to come back before we re-enable


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as fh:
            return json.load(fh)
    return {}


def save_config(config):
    with open(CONFIG_PATH, "w") as fh:
        json.dump(config, fh, indent=2)
    os.chmod(CONFIG_PATH, 0o600)  # token is sensitive


def _local_ip():
    """Best-effort LAN IP of the interface that routes to the server, so the
    Print Agents page can show where this Pi lives (no network scanning needed).
    Opening a UDP socket sends nothing — it just makes the OS pick the route."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:  # noqa: BLE001 - reporting location is best-effort
        return ""


def _identity_headers():
    """Hostname + LAN IP headers the server stores for the Print Agents page."""
    headers = {}
    try:
        host = socket.gethostname()
        if host:
            headers["X-Agent-Hostname"] = host
    except Exception:  # noqa: BLE001
        pass
    ip = _local_ip()
    if ip:
        headers["X-Agent-Local-IP"] = ip
    return headers


def cmd_pair(args):
    server = args.server.rstrip("/")
    resp = requests.post(
        f"{server}/checkin/api/print/pair",
        json={"pairing_code": args.code},
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code != 200:
        sys.exit(f"Pairing failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    config = load_config()
    config.update({"server": server, "token": data["token"], "agent_name": data.get("agent_name")})
    if args.printer:
        config["printer"] = args.printer
    save_config(config)
    print(f"Paired as '{data.get('agent_name')}'. Config saved to {CONFIG_PATH}")
    print("Start printing with:  python3 anchorpoint_agent.py run")


DEFAULT_MEDIA_WIDTH_MM = 62   # Brother QL continuous-roll width
DEFAULT_CUT_MEDIA = "EndOfPage"   # cut after every label (Brother QL roll)

# Cache per printer so we don't shell out to lpoptions for every job.
_cut_support_cache = {}


def _printer_supports_cut(printer):
    """True if the CUPS queue exposes a CutMedia option.

    Brother QL roll printers do (and default to NOT cutting between labels, so
    batches come out as one strip unless we ask). Rollo/Zebra-style printers
    typically don't expose it — we only pass the cut option where it's
    understood, so it's a harmless no-op everywhere else. Cached per printer.
    """
    key = printer or ""
    if key in _cut_support_cache:
        return _cut_support_cache[key]
    supported = False
    try:
        cmd = ["lpoptions"]
        if printer:
            cmd += ["-p", printer]
        cmd += ["-l"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        supported = any(
            line.startswith("CutMedia") for line in out.stdout.splitlines()
        )
    except Exception:  # noqa: BLE001 - if we can't tell, don't pass the option
        supported = False
    _cut_support_cache[key] = supported
    return supported


def _png_size(png_bytes):
    """Width/height in pixels from the PNG IHDR header (no Pillow needed)."""
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = int.from_bytes(png_bytes[16:20], "big")
    height = int.from_bytes(png_bytes[20:24], "big")
    return width, height


_REQUEST_ID_RE = re.compile(r"request id is (\S+)")


def _parse_request_id(stdout):
    """Pull the CUPS job id out of `lp` stdout, e.g.
    'request id is ChurchLabel-34 (1 file(s))' -> 'ChurchLabel-34'.
    None if it can't be found (then we skip the wait and behave as before)."""
    match = _REQUEST_ID_RE.search(stdout or "")
    return match.group(1) if match else None


def _wait_for_job(job_id, timeout=JOB_DONE_TIMEOUT_SECONDS):
    """Block until CUPS job `job_id` leaves the active queue (printed or failed)
    or `timeout` seconds elapse. Best-effort: if `lpstat` is unavailable we
    return immediately rather than stalling the agent."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            out = subprocess.run(
                ["lpstat", "-W", "not-completed", "-o"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:  # noqa: BLE001 - can't query the queue; don't block the agent
            return
        # `lpstat -o` lines begin with the request id ("ChurchLabel-34 user ...").
        active = [line.split(" ", 1)[0] for line in (out.stdout or "").splitlines()]
        if job_id not in active:
            return
        time.sleep(JOB_POLL_SECONDS)


def _print_png(png_bytes, printer, width_mm=DEFAULT_MEDIA_WIDTH_MM,
               cut_media=DEFAULT_CUT_MEDIA):
    """Send a PNG to the printer via CUPS `lp`. Returns (ok, error_message).

    Brother QL printers reject jobs whose page size doesn't fit the loaded
    media ("file size too large"), so compute the physical label size from the
    image dimensions and pass it explicitly with fit scaling. width_mm comes
    from the server per job (the agent's configured label width); the cut
    length follows the artwork's aspect ratio so wider media scales up
    proportionally.

    Each label is its own job, so we ask the printer to cut at the end of the
    page (cut_media, default "EndOfPage") — otherwise Brother QL roll queues
    print a whole pre-print batch as one uncut strip. Only passed when the
    queue actually exposes CutMedia, so it's a no-op on printers without it.
    Set cut_media to "" / None to disable.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(png_bytes)
            tmp_path = tmp.name
        cmd = ["lp"]
        if printer:
            cmd += ["-d", printer]
        size = _png_size(png_bytes)
        if size:
            # Aspect-derived cut length, rounded up a couple of mm so nothing clips.
            height_mm = max(20, round(width_mm * size[1] / size[0]) + 2)
            cmd += [
                "-o", f"media=Custom.{width_mm}x{height_mm}mm",
                "-o", "print-scaling=fit",
            ]
        if cut_media and _printer_supports_cut(printer):
            cmd += ["-o", f"CutMedia={cut_media}"]
        cmd.append(tmp_path)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "lp failed").strip()
        # `lp` returns as soon as the job is QUEUED, not printed. Wait for it to
        # finish feeding so the caller doesn't pile the next label onto the
        # printer mid-job (which wedges the ipp-usb USB bridge under batches).
        job_id = _parse_request_id(result.stdout)
        if job_id:
            _wait_for_job(job_id)
            time.sleep(JOB_SETTLE_SECONDS)
        return True, ""
    except Exception as exc:  # noqa: BLE001 - report any failure back to the server
        return False, str(exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


_last_recovery = 0.0


def _recover_print_subsystem(printer):
    """Best-effort recovery after a failed print so the printer comes back
    without a manual Pi reboot: clear stuck jobs, bounce ipp-usb + cups (wakes a
    USB bridge that autosuspended while idle), then re-enable the queue (CUPS
    disables it after a job errors). Rate-limited and never raises — if the sudo
    grant is missing the service restarts simply no-op and the agent carries on.
    """
    global _last_recovery
    if not RECOVER_AFTER_FAILURE:
        return
    now = time.monotonic()
    if _last_recovery and now - _last_recovery < RECOVERY_COOLDOWN_SECONDS:
        return  # already tried very recently; don't bounce cups on every poll
    _last_recovery = now
    print("Print failed — recovering the print subsystem "
          "(clear queue, restart ipp-usb/cups, re-enable queue)...", file=sys.stderr)

    def _try(cmd):
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception as exc:  # noqa: BLE001 - recovery is best-effort
            print(f"  recovery step {cmd!r} failed (non-fatal): {exc}", file=sys.stderr)

    _try(["cancel", "-a"])
    _try(["sudo", "-n", "systemctl", "restart", "ipp-usb"])  # wake the USB bridge
    _try(["sudo", "-n", "systemctl", "restart", "cups"])
    time.sleep(RECOVERY_SETTLE_SECONDS)                      # let the daemon come back up
    if printer:
        _try(["cupsaccept", printer])   # member of lpadmin (install.sh) — no sudo needed
        _try(["cupsenable", printer])
    _cut_support_cache.clear()           # the queue may have been re-created


def cmd_run(args):
    config = load_config()
    server = config.get("server")
    token = config.get("token")
    if not server or not token:
        sys.exit("Not paired yet. Run the 'pair' command first.")
    printer = args.printer or config.get("printer")
    save_dir = args.save_dir
    once = args.once
    # Cut after each label unless explicitly disabled (--no-cut, or
    # "cut_media": "" in the config). Default "EndOfPage".
    cut_media = "" if args.no_cut else config.get("cut_media", DEFAULT_CUT_MEDIA)
    headers = {"Authorization": f"Bearer {token}"}
    # Tell the server where this Pi is (shown on the Print Agents page) so it can
    # be found without scanning the LAN. Computed once at startup; a restart
    # after a venue/IP change refreshes it.
    headers.update(_identity_headers())

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)

    print(f"AnchorPoint agent '{config.get('agent_name')}' polling {server}")
    print(f"Output: {('saving PNGs to ' + save_dir) if save_dir else (printer or 'system default printer')}")

    while True:
        try:
            resp = requests.get(
                f"{server}/checkin/api/print/next", headers=headers, timeout=HTTP_TIMEOUT
            )
            if resp.status_code == 401:
                sys.exit("Token rejected. Re-pair this agent in AnchorPoint settings.")
            if resp.status_code == 204:
                if once:
                    print("No pending jobs.")
                    return
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            if resp.status_code != 200:
                print(f"Poll error {resp.status_code}: {resp.text}", file=sys.stderr)
                if once:
                    return
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            job = resp.json()
            img = requests.get(
                f"{server}{job['image_url']}", headers=headers, timeout=HTTP_TIMEOUT
            )
            if img.status_code != 200:
                _ack(server, headers, job["id"], False, f"image fetch {img.status_code}")
                continue

            if save_dir:
                # Debug mode: write the label to a folder instead of printing —
                # useful for validating the pipeline before CUPS/the printer is set up.
                path = os.path.join(save_dir, f"job-{job['id']}.png")
                with open(path, "wb") as fh:
                    fh.write(img.content)
                ok, err = True, ""
            else:
                width_mm = job.get("media_width_mm") or DEFAULT_MEDIA_WIDTH_MM
                ok, err = _print_png(img.content, printer, width_mm, cut_media)

            _ack(server, headers, job["id"], ok, err)
            label = job.get("description") or job.get("kind")
            verb = "saved" if (save_dir and ok) else ("printed" if ok else f"FAILED ({err}):")
            print(f"{verb} {label}")
            if not ok and not save_dir:
                # Try to self-heal a wedged printer so the next check-in prints
                # without a manual Pi reboot.
                _recover_print_subsystem(printer)
            # Loop straight to the next job. _print_png blocks until this label
            # has finished printing, so a batch feeds one label at a time instead
            # of flooding the queue (which wedges ipp-usb over USB).
        except requests.RequestException as exc:
            print(f"Network error: {exc}", file=sys.stderr)
            if once:
                return
            time.sleep(POLL_INTERVAL_SECONDS)


def _ack(server, headers, job_id, ok, error=""):
    try:
        requests.post(
            f"{server}/checkin/api/print/{job_id}/ack",
            headers=headers,
            json={"status": "printed" if ok else "failed", "error": error},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"Failed to ack job {job_id}: {exc}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="AnchorPoint print agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pair = sub.add_parser("pair", help="Pair this agent with AnchorPoint")
    p_pair.add_argument("--server", required=True, help="AnchorPoint base URL")
    p_pair.add_argument("--code", required=True, help="Pairing code from Settings")
    p_pair.add_argument("--printer", help="CUPS printer name (optional)")
    p_pair.set_defaults(func=cmd_pair)

    p_run = sub.add_parser("run", help="Poll for and print labels")
    p_run.add_argument("--printer", help="CUPS printer name (overrides config)")
    p_run.add_argument("--save-dir", dest="save_dir",
                       help="Debug: save label PNGs to this folder instead of printing")
    p_run.add_argument("--once", action="store_true",
                       help="Process pending jobs then exit (don't keep polling)")
    p_run.add_argument("--no-cut", dest="no_cut", action="store_true",
                       help="Don't ask the printer to cut between labels")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
