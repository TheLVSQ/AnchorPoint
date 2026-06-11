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
#   3. Optionally creates a driverless CUPS queue for a network printer
#   4. Pairs the agent with your AnchorPoint server
#   5. Installs + starts a systemd service so it survives reboots

set -euo pipefail

SERVER=""
CODE=""
PRINTER_URI=""
PRINTER=""
QUEUE_NAME="ChurchLabel"
INSTALL_DIR="/opt/anchorpoint-agent"
SERVICE_NAME="anchorpoint-agent"

usage() {
    grep "^#" "$0" | head -16
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --server)      SERVER="$2"; shift 2 ;;
        --code)        CODE="$2"; shift 2 ;;
        --printer-uri) PRINTER_URI="$2"; shift 2 ;;
        --printer)     PRINTER="$2"; shift 2 ;;
        --queue-name)  QUEUE_NAME="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

[[ -n "$SERVER" && -n "$CODE" ]] || { echo "ERROR: --server and --code are required."; usage; }
[[ $EUID -eq 0 ]] || { echo "ERROR: run with sudo."; exit 1; }
SERVER="${SERVER%/}"

# The agent runs as the user who invoked sudo (falls back to 'pi').
RUN_USER="${SUDO_USER:-pi}"
id "$RUN_USER" >/dev/null 2>&1 || { echo "ERROR: user '$RUN_USER' not found. Re-run with sudo from a normal user."; exit 1; }

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
if [[ -z "$PRINTER" ]]; then
    echo "NOTE: no --printer-uri/--printer given; the agent will use the system default printer."
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
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "✓ Print agent installed and running."
    echo "  Now open AnchorPoint > Check-In > Print Agents and click 'Test Print'."
    echo "  Watch logs any time with:  journalctl -u $SERVICE_NAME -f"
else
    echo ""
    echo "✗ The service did not start. Check:  journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi
