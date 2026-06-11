# Check-In Label Printing on a Raspberry Pi (fresh-Pi guide)

AnchorPoint prints check-in labels through a small **print agent** that runs on
a Raspberry Pi next to the printer. The agent **polls the server over outbound
HTTPS** — there is no VPN, no Tailscale, no port forwarding, and the server
never needs to reach into the church network.

```
tablet (kiosk)  ─►  AnchorPoint server  ◄─ poll ─  Pi print agent  ─►  label printer
```

Anyone comfortable flashing an SD card can do this start to finish in ~20
minutes. No developer needed.

## What to buy

- **Raspberry Pi Zero 2 W** (recommended — small, ~$15) or any Pi 3 or newer
- MicroSD card (8GB+) and a power supply
- A label printer (see [Supported printers](#supported-printers) — simplest
  answer: **Brother QL-8xx series** with 62mm continuous rolls, e.g. DK-2205)

## Step 1: Flash the SD card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on any computer.
2. Choose **Raspberry Pi OS Lite** (64-bit, no desktop needed).
3. Click the gear/"Edit settings" before writing and set:
   - **Hostname**: e.g. `church-print`
   - **Username/password**: e.g. `pi` / a real password
   - **Wi-Fi**: your church network SSID + password
   - **Enable SSH** (password authentication is fine)
4. Write the card, put it in the Pi, power it on, give it a minute.

## Step 2: Create the agent in AnchorPoint

In AnchorPoint go to **Check-In → Print Agents → Add Agent** and name it
(e.g. "Lobby Printer"). The page shows:

- an 8-character **pairing code** (valid 15 minutes), and
- a **copy-paste install command** with the code already filled in.

## Step 3: Run the one-command install

From any computer on the same network:

```bash
ssh pi@church-print.local
```

Paste the command from the Print Agents page, filling in your printer's IP
address (printable from the printer's own menu, or look in your router's
device list):

```bash
curl -fsSL https://YOUR-ANCHORPOINT/checkin/agent/install.sh | sudo bash -s -- \
    --server https://YOUR-ANCHORPOINT \
    --code YOURCODE1 \
    --printer-uri ipp://PRINTER-IP/ipp/print
```

This installs CUPS and the agent, creates a driverless print queue, pairs with
the server, and starts a **systemd service** that auto-starts on boot and
restarts on failure.

## Step 4: Test

Back on the Print Agents page the agent should show **Online** within a
minute. Click **Test Print** — a test label should come out. Done: from now on
kiosk check-ins print automatically.

If your labels are not on a 62mm roll, set **Label width (mm)** for this agent
on the same page (e.g. 102 for a 4" Zebra roll).

## Supported printers

The agent prints through CUPS, so the rule is: **the printer must either speak
IPP over the network (most modern label printers) or have a Linux/CUPS
driver.** Guidance for purchasing:

| Printer | How | Notes |
|---|---|---|
| Brother QL-8xx (QL-810W/820NWB...) | `--printer-uri ipp://<ip>/ipp/print` | The easy path. 62mm continuous roll (DK-2205). **Buy this for new stations.** |
| Zebra ZD500 / Link-OS | CUPS Zebra (ZPL) driver, USB or network | Add the queue manually (appendix), then `--printer <queue>`. Set the agent's label width to the loaded roll. |
| Generic/Amazon thermal printers | Varies | Only buy if the listing explicitly mentions Linux/CUPS support or AirPrint/IPP. Otherwise avoid. |

## Day-to-day operations

```bash
journalctl -u anchorpoint-agent -f      # watch labels print, see errors
sudo systemctl restart anchorpoint-agent
sudo systemctl status anchorpoint-agent
```

- **Agent shows Offline** — Pi off/lost Wi-Fi, or the service stopped (check status above).
- **Re-pair** (e.g. after replacing the Pi): Print Agents → **Re-pair** → run the
  install one-liner again with the new code. Safe to re-run; it updates in place.
- **Important**: only one agent should be active — if two paired agents are
  running, jobs alternate between them. Remove old agents from the Print
  Agents page when you retire their hardware.

## Appendix: manual CUPS queue (USB / non-IPP printers)

For printers the driverless path can't handle (USB-only Brother, Zebra ZPL):

```bash
sudo apt install -y printer-driver-all        # or the vendor's .deb driver
lpinfo -v                                     # find the device URI (usb://...)
sudo lpadmin -p ChurchLabel -E -v 'usb://...' -m <driver-from-lpinfo -m>
lp -d ChurchLabel test.png                    # verify CUPS prints
```

Then run the install one-liner with `--printer ChurchLabel` instead of
`--printer-uri`. The reference systemd unit lives at
[agent/anchorpoint-agent.service](../agent/anchorpoint-agent.service) if you
need to install the service by hand.
