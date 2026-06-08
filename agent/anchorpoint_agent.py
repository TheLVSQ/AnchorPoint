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


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as fh:
            return json.load(fh)
    return {}


def save_config(config):
    with open(CONFIG_PATH, "w") as fh:
        json.dump(config, fh, indent=2)
    os.chmod(CONFIG_PATH, 0o600)  # token is sensitive


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


def _print_png(png_bytes, printer):
    """Send a PNG to the printer via CUPS `lp`. Returns (ok, error_message)."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(png_bytes)
            tmp_path = tmp.name
        cmd = ["lp"]
        if printer:
            cmd += ["-d", printer]
        cmd.append(tmp_path)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "lp failed").strip()
        return True, ""
    except Exception as exc:  # noqa: BLE001 - report any failure back to the server
        return False, str(exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def cmd_run(args):
    config = load_config()
    server = config.get("server")
    token = config.get("token")
    if not server or not token:
        sys.exit("Not paired yet. Run the 'pair' command first.")
    printer = args.printer or config.get("printer")
    headers = {"Authorization": f"Bearer {token}"}

    print(f"AnchorPoint agent '{config.get('agent_name')}' polling {server}")
    print(f"Printing to: {printer or 'system default printer'}")

    while True:
        try:
            resp = requests.get(
                f"{server}/checkin/api/print/next", headers=headers, timeout=HTTP_TIMEOUT
            )
            if resp.status_code == 401:
                sys.exit("Token rejected. Re-pair this agent in AnchorPoint settings.")
            if resp.status_code == 204:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            if resp.status_code != 200:
                print(f"Poll error {resp.status_code}: {resp.text}", file=sys.stderr)
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            job = resp.json()
            img = requests.get(
                f"{server}{job['image_url']}", headers=headers, timeout=HTTP_TIMEOUT
            )
            if img.status_code != 200:
                _ack(server, headers, job["id"], False, f"image fetch {img.status_code}")
                continue

            ok, err = _print_png(img.content, printer)
            _ack(server, headers, job["id"], ok, err)
            label = job.get("description") or job.get("kind")
            print(("printed" if ok else f"FAILED ({err}):") + f" {label}")
            # Drain the rest of the batch immediately rather than waiting.
        except requests.RequestException as exc:
            print(f"Network error: {exc}", file=sys.stderr)
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
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
