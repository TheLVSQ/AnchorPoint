# Check-In Printing via Raspberry Pi (Pi 3 compatible)

This setup lets AnchorPoint running on a VPS print labels to a local USB/network printer by routing jobs through a Raspberry Pi print server.

## Why this is needed

- Your AnchorPoint app runs on a remote server (DigitalOcean VPS).
- A local printer IP (e.g. `192.168.x.x`) is not reachable from that VPS.
- A Raspberry Pi on the same local network as the printer can bridge that gap.

## Recommended architecture

1. Printer connected to Raspberry Pi (USB or LAN).
2. Pi runs CUPS with a named queue.
3. VPS reaches Pi over a secure private network (recommended: Tailscale).
4. AnchorPoint printer config uses `printer_type=cups` and `host=<cups_queue_name>`.
5. Print jobs execute in the AnchorPoint container and are sent to CUPS on the Pi.

## Raspberry Pi requirements

- Raspberry Pi 3 is sufficient for this workload.
- Raspberry Pi OS Lite (64-bit) recommended.
- Stable network and static/reserved IP.

## Step 1: Install CUPS on the Pi

```bash
sudo apt update
sudo apt install -y cups printer-driver-all avahi-daemon
sudo usermod -aG lpadmin pi
sudo systemctl enable --now cups
```

Edit CUPS config:

```bash
sudo nano /etc/cups/cupsd.conf
```

Ensure CUPS listens on the network:

```conf
Port 631
Listen /run/cups/cups.sock
```

And allow access from trusted networks only (adjust CIDR):

```conf
<Location />
  Order allow,deny
  Allow 127.0.0.1
  Allow 192.168.0.0/16
</Location>

<Location /admin>
  Order allow,deny
  Allow 127.0.0.1
  Allow 192.168.0.0/16
</Location>
```

Restart:

```bash
sudo systemctl restart cups
```

## Step 2: Add printer queue on the Pi

Use CUPS UI at `http://<pi-ip>:631/admin` and create a queue.

Example queue name:

- `brother_ql_820nwb`

Verify queue exists:

```bash
lpstat -p
```

## Step 3: Private networking between VPS and Pi (recommended)

Use Tailscale on both the VPS and the Pi so the VPS can reach the Pi securely without exposing CUPS publicly.

Install and connect Tailscale on both hosts, then confirm:

```bash
tailscale status
```

From VPS:

```bash
curl http://<pi-tailscale-ip>:631/printers/
```

## Step 4: Configure AnchorPoint container to use remote CUPS

Set CUPS server for the web container (in Docker env for `web` service):

```env
CUPS_SERVER=<pi-tailscale-ip>:631
```

Rebuild/restart web container after env changes.

## Step 5: Configure printer in AnchorPoint UI

In `Check-In > Printers`, create printer with:

- `Name`: human-readable (e.g. `Kids Label Printer`)
- `Printer Type`: `cups`
- `Host`: **CUPS queue name** from Pi (e.g. `brother_ql_820nwb`)
- `Port`: optional/unused for CUPS queue mode
- `Is Active`: enabled
- `Is Default`: enabled (if primary)

Then run **Test Print** in the UI.

## Health chip behavior

Kiosk health chip shows:

- configured/not configured
- online/offline status
- `last_successful_print_at` timestamp

`last_successful_print_at` updates when test print or check-in print fully succeeds.

## Troubleshooting

- **Printer shows offline**: verify Pi queue name and `lpstat -p` output.
- **No jobs arriving**: check `CUPS_SERVER` in container env and restart web service.
- **Job appears in CUPS but not printed**: verify Pi-side driver and local printer connectivity.
- **Intermittent failures**: use wired Ethernet for Pi/printer where possible.

