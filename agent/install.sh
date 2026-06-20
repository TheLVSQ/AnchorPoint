#!/usr/bin/env bash
# AnchorPoint print-agent installer for Raspberry Pi / Debian.
#
# Run the one-liner shown on AnchorPoint's Check-In > Print Agents page:
#
#   curl -fsSL https://<your-anchorpoint>/checkin/agent/install.sh | sudo bash -s -- \
#       --server https://<your-anchorpoint> --code ABCD1234 \
#       --printer-uri ipp://<printer-ip>/ipp/print
#
# What it does (idempotent — safe to re-run):
#   1. Installs CUPS + python3-requests
#   2. Downloads the agent to /opt/anchorpoint-agent/
#   3. Optionally creates a CUPS queue for the printer:
#        --printer-uri ipp://IP/ipp/print   network (driverless)
#        --printer-usb [--driver zebra]      auto-detect a USB printer; --driver
#                                            picks a matching PPD (else driverless)
#        --printer EXISTING-QUEUE            use a queue you already made
#   4. Pairs the agent with your AnchorPoint server
#   5. Installs + starts a systemd service so it survives reboots
#   6. Installs the comitup WiFi fallback (skip with --no-wifi-fallback): if the
#      Pi can't reach a known network it broadcasts its own 'comitup-<id>' AP so
#      you can join a new venue's WiFi from a phone. Needs a reboot to activate.

set -euo pipefail

SERVER=""
CODE=""
PRINTER_URI=""
PRINTER=""
PRINTER_USB=0
DRIVER_MATCH=""
QUEUE_NAME="ChurchLabel"
INSTALL_DIR="/opt/anchorpoint-agent"
SERVICE_NAME="anchorpoint-agent"
WIFI_FALLBACK=1
# Pinned comitup repo-source package (adds davesteele's apt repo + signing key).
COMITUP_APT_SOURCE_URL="https://davesteele.github.io/comitup/deb/davesteele-comitup-apt-source_1.3_all.deb"

usage() {
    grep "^#" "$0" | head -23
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --server)           SERVER="$2"; shift 2 ;;
        --code)             CODE="$2"; shift 2 ;;
        --printer-uri)      PRINTER_URI="$2"; shift 2 ;;
        --printer-usb)      PRINTER_USB=1; shift ;;
        --driver)           DRIVER_MATCH="$2"; shift 2 ;;
        --printer)          PRINTER="$2"; shift 2 ;;
        --queue-name)       QUEUE_NAME="$2"; shift 2 ;;
        --no-wifi-fallback) WIFI_FALLBACK=0; shift ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

[[ -n "$SERVER" && -n "$CODE" ]] || { echo "ERROR: --server and --code are required."; usage; }
[[ $EUID -eq 0 ]] || { echo "ERROR: run with sudo."; exit 1; }
SERVER="${SERVER%/}"

# The agent runs as the user who invoked sudo (falls back to 'pi').
RUN_USER="${SUDO_USER:-pi}"
id "$RUN_USER" >/dev/null 2>&1 || { echo "ERROR: user '$RUN_USER' not found. Re-run with sudo from a normal user."; exit 1; }

# Install the comitup WiFi-bootstrap fallback. Non-fatal: any failure here just
# skips the fallback — the print agent itself is already installed. Hands WiFi
# to NetworkManager (comitup's backend) and needs a reboot to activate, which we
# deliberately DON'T do here (a reboot mid curl|bash would sever the SSH run).
setup_wifi_fallback() {
    if dpkg -s comitup >/dev/null 2>&1; then
        echo "==> WiFi fallback (comitup) already installed — skipping."
        return 0
    fi
    echo "==> Installing WiFi fallback (comitup)..."
    local deb="/tmp/davesteele-comitup-apt-source.deb"
    if ! curl -fsSL "$COMITUP_APT_SOURCE_URL" -o "$deb"; then
        echo "   WARNING: couldn't fetch the comitup repo package — skipping WiFi fallback."
        return 0
    fi
    dpkg -i --force-all "$deb" >/dev/null 2>&1 || true
    rm -f "$deb"
    apt-get update -qq || true
    if ! apt-get install -y -qq comitup >/dev/null 2>&1; then
        echo "   WARNING: comitup install failed — skipping WiFi fallback (the print agent is fine)."
        return 0
    fi
    # Let NetworkManager own the interfaces; mask the legacy/conflicting managers.
    rm -f /etc/network/interfaces
    systemctl mask dnsmasq.service systemd-resolved.service dhcpcd.service wpa-supplicant.service >/dev/null 2>&1 || true
    systemctl enable NetworkManager.service >/dev/null 2>&1 || true
    WIFI_FALLBACK_DONE=1
    echo "    comitup installed. Reboot to activate it."
}

echo "==> Installing packages (CUPS + Python requests)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends cups cups-ipp-utils python3-requests curl >/dev/null
systemctl enable --now cups >/dev/null 2>&1 || true
usermod -aG lp,lpadmin "$RUN_USER" 2>/dev/null || usermod -aG lp "$RUN_USER"

echo "==> Installing the print agent to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
curl -fsSL "$SERVER/checkin/agent/anchorpoint_agent.py" -o "$INSTALL_DIR/anchorpoint_agent.py"
chown -R "$RUN_USER":"$RUN_USER" "$INSTALL_DIR"

if [[ -n "$PRINTER_URI" ]]; then
    echo "==> Creating driverless CUPS queue '$QUEUE_NAME' -> $PRINTER_URI..."
    lpadmin -p "$QUEUE_NAME" -E -v "$PRINTER_URI" -m everywhere
    cupsenable "$QUEUE_NAME" || true
    cupsaccept "$QUEUE_NAME" || true
    PRINTER="$QUEUE_NAME"
fi
if [[ "$PRINTER_USB" == "1" && -z "$PRINTER" ]]; then
    echo "==> Detecting USB printer..."
    USB_URI="$(lpinfo -v 2>/dev/null | awk '$2 ~ /^usb:/ {print $2; exit}')"
    if [[ -z "$USB_URI" ]]; then
        echo "ERROR: --printer-usb given but no USB printer found (plugged in and powered on?)."
        echo "       Devices CUPS can see:"
        lpinfo -v 2>/dev/null | sed 's/^/         /'
        exit 1
    fi
    PPD_ARG="-m everywhere"
    if [[ -n "$DRIVER_MATCH" ]]; then
        PPD="$(lpinfo -m 2>/dev/null | grep -i -- "$DRIVER_MATCH" | head -1 | awk '{print $1}')"
        if [[ -n "$PPD" ]]; then
            PPD_ARG="-m $PPD"
            echo "    Driver: $PPD"
        else
            echo "    WARNING: no installed driver matched '$DRIVER_MATCH'; using driverless."
        fi
    fi
    echo "==> Creating USB CUPS queue '$QUEUE_NAME' -> $USB_URI..."
    # shellcheck disable=SC2086
    lpadmin -p "$QUEUE_NAME" -E -v "$USB_URI" $PPD_ARG
    cupsenable "$QUEUE_NAME" || true
    cupsaccept "$QUEUE_NAME" || true
    PRINTER="$QUEUE_NAME"
fi
if [[ -z "$PRINTER" ]]; then
    echo "NOTE: no --printer-uri/--printer-usb/--printer given; the agent will use the system default printer."
elif lpoptions -p "$PRINTER" -l 2>/dev/null | grep -q "^CutMedia"; then
    # Brother QL roll printers: cut after every label, or batches come out as
    # one long uncut strip. Set the queue default for any printing path; the
    # agent also passes this per job, so cutting works even on queues we didn't
    # create here. Harmless no-op for printers without the option.
    lpadmin -p "$PRINTER" -o CutMedia-default=EndOfPage
    echo "==> Enabled cut-after-each-label on '$PRINTER'."
fi

echo "==> Pairing with $SERVER..."
CONFIG="$INSTALL_DIR/config.json"
sudo -u "$RUN_USER" ANCHORPOINT_AGENT_CONFIG="$CONFIG" \
    python3 "$INSTALL_DIR/anchorpoint_agent.py" pair \
    --server "$SERVER" --code "$CODE" ${PRINTER:+--printer "$PRINTER"}

echo "==> Installing systemd service..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<UNIT
[Unit]
Description=AnchorPoint print agent (polls for check-in labels and prints them)
After=network-online.target cups.service
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Environment=ANCHORPOINT_AGENT_CONFIG=$CONFIG
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $INSTALL_DIR/anchorpoint_agent.py run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

sleep 3
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "✗ The service did not start. Check:  journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi

if [[ "$WIFI_FALLBACK" == "1" ]]; then
    setup_wifi_fallback || true
fi

echo ""
echo "✓ Print agent installed and running."
echo "  Now open AnchorPoint > Check-In > Print Agents and click 'Test Print'."
echo "  Watch logs any time with:  journalctl -u $SERVICE_NAME -f"
if [[ "${WIFI_FALLBACK_DONE:-0}" == "1" ]]; then
    echo ""
    echo "  WiFi fallback (comitup) installed — REBOOT to activate:  sudo reboot"
    echo "  At a venue with no known WiFi the Pi makes a 'comitup-<id>' hotspot;"
    echo "  connect to it and open http://10.41.0.1 to add a network."
fi
