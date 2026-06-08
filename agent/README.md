# AnchorPoint Print Agent

A small helper that runs next to your label printer and prints check-in tags
automatically. It **polls** your AnchorPoint server over outbound HTTPS — there
is **no inbound networking, no VPN, and no port forwarding** to configure. Put
it on a Raspberry Pi (recommended) or any always-on computer on the same network
as the printer.

```
iPad / computer (check-in)  ─►  AnchorPoint (server)  ◄─poll─  this agent  ─►  printer
```

## Requirements

- Python 3.8+ and `pip install -r requirements.txt` (just `requests`).
- A printer installed in **CUPS** on this machine. The agent prints with `lp`,
  so if `lp -d <printer> file.png` works, the agent works. For a Raspberry Pi +
  Brother QL label printer, follow `docs/checkin-printer-raspberry-pi.md` (CUPS
  install + driver + queue) — but **stop before the Tailscale section**; you
  don't need it with this agent.

## Setup

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
