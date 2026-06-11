# AnchorPoint Print Agent

A small helper that runs next to your label printer and prints check-in tags
automatically. It **polls** your AnchorPoint server over outbound HTTPS — there
is **no inbound networking, no VPN, and no port forwarding** to configure. Put
it on a Raspberry Pi (recommended) or any always-on computer on the same network
as the printer.

```
iPad / computer (check-in)  ─►  AnchorPoint (server)  ◄─poll─  this agent  ─►  printer
```

## Quick install (Raspberry Pi / Debian — recommended)

In AnchorPoint: **Check-In → Print Agents → Add Agent**. The page shows a
ready-to-paste one-liner containing your pairing code:

```bash
curl -fsSL https://<your-anchorpoint>/checkin/agent/install.sh | sudo bash -s -- \
    --server https://<your-anchorpoint> --code <PAIRING_CODE> \
    --printer-uri ipp://<printer-ip>/ipp/print
```

That installs CUPS + the agent, creates a driverless queue for a network
printer, pairs, and starts a systemd service that survives reboots. Full
fresh-Pi walkthrough (from blank SD card): `docs/checkin-printer-raspberry-pi.md`.
Label media width is configured per agent on the Print Agents page (default
62mm Brother roll).

## Manual setup

### Requirements

- Python 3.8+ and `pip install -r requirements.txt` (just `requests`).
- A printer installed in **CUPS** on this machine. The agent prints with `lp`,
  so if `lp -d <printer> file.png` works, the agent works.

### Steps

1. In AnchorPoint: **Settings → Print Agents → Add Agent**. Copy the pairing code.
2. On this machine:
   ```bash
   pip install -r requirements.txt
   python3 anchorpoint_agent.py pair --server https://your-anchorpoint-url --code <PAIRING_CODE> --printer <CUPS_PRINTER_NAME>
   python3 anchorpoint_agent.py run
   ```
   (`--printer` is optional; omit it to use the system default printer. Find
   names with `lpstat -p`.)

When a family checks in, their labels print automatically. The pairing code is
one-time; after pairing, the agent stores a token in `~/.anchorpoint_agent.json`.

### Test the pipeline before the printer is set up

To confirm the agent can reach the server and pull labels — without a working
printer yet — save labels to a folder instead of printing, and process the queue
once:

```bash
python3 anchorpoint_agent.py run --once --save-dir ./test-labels
```

Do a check-in (or Settings → Print Agents → Test Print), run the command, and
you should see PNG label files appear in `./test-labels`. Once that works, drop
the `--save-dir`/`--once` flags to print for real.

## Run it as a service (Raspberry Pi / systemd)

Create `/etc/systemd/system/anchorpoint-agent.service`:

```ini
[Unit]
Description=AnchorPoint Print Agent
After=network-online.target cups.service
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/agent/anchorpoint_agent.py run
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable --now anchorpoint-agent
journalctl -u anchorpoint-agent -f   # watch it print
```

## Troubleshooting

- **"Token rejected"** — re-pair: get a fresh code in Settings → Print Agents → Re-pair.
- **Nothing prints, no errors** — confirm the printer name: `lpstat -p`, then test `lp -d <name> somefile.png`.
- **Agent shows "Offline" in AnchorPoint** — it isn't running or can't reach the
  server; check `journalctl -u anchorpoint-agent` and that the server URL is correct.
