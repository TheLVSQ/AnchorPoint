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
#        --printer-usb [--driver zebra]      auto-detect a USB printer (incl.
#                                            ipp-usb ones like the Brother QL);
#                                            --driver picks a PPD (else driverless)
#        --printer EXISTING-QUEUE            use a queue you already made
#        --brother-ql [--ql-device usb://0x04f9:0xNNNN] [--ql-label 62]
#                                            Brother QL over DIRECT USB via the
#                                            brother_ql driver — no CUPS, no
#                                            ipp-usb. The reliable path for QL
#                                            label printers (auto-detects the
#                                            USB device if --ql-device omitted).
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
BROTHER_QL=0
QL_MODEL="QL-820NWB"
QL_LABEL="62"
QL_DEVICE=""
# Pinned comitup repo-source package (adds davesteele's apt repo + signing key).
COMITUP_APT_SOURCE_URL="https://davesteele.github.io/comitup/deb/davesteele-comitup-apt-source_1.3_all.deb"

usage() {
    grep "^#" "$0" | head -29
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
        --brother-ql)       BROTHER_QL=1; shift ;;
        --ql-model)         QL_MODEL="$2"; shift 2 ;;
        --ql-label)         QL_LABEL="$2"; shift 2 ;;
        --ql-device)        QL_DEVICE="$2"; shift 2 ;;
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

# True if a USB printer is physically attached — USB interface class 07 is
# "printer". Independent of whether CUPS shows a raw usb:// device, because
# modern Brother / IPP-over-USB printers get claimed by ipp-usb and never appear
# as usb:// (they're re-exposed as a local IPP service instead).
usb_printer_present() {
    grep -qsx 07 /sys/bus/usb/devices/*/bInterfaceClass 2>/dev/null \
        || lpinfo -v 2>/dev/null | grep -qi '(usb)._ipp._tcp.local'
}

# Keep the printer reachable after the Pi sits idle. On a Pi print appliance the
# two known culprits are USB autosuspend (powers the printer's USB port down; the
# ipp-usb bridge to a Brother QL then won't wake, so the next check-in silently
# doesn't print until a reboot) and onboard WiFi power-save (drops the link).
# Disable both, and grant the agent a tiny, bounded sudo right so it can restart
# the print stack itself after a failed print instead of waiting for a reboot.
harden_print_reliability() {
    echo "==> Hardening print reliability (USB autosuspend off, WiFi power-save off)..."

    # 1. Never autosuspend USB on this appliance — keeps the printer awake.
    cat > /etc/udev/rules.d/99-anchorpoint-usb-no-suspend.rules <<'RULE'
# AnchorPoint: keep USB devices (the label printer) powered so they don't sleep
# while the Pi is idle and then fail to wake on the next print job.
ACTION=="add", SUBSYSTEM=="usb", TEST=="power/control", ATTR{power/control}="on"
RULE
    udevadm control --reload-rules >/dev/null 2>&1 || true
    udevadm trigger --action=add --subsystem-match=usb >/dev/null 2>&1 || true
    # Apply to already-connected devices right now (the rule covers future plug-ins).
    for f in /sys/bus/usb/devices/*/power/control; do
        echo on > "$f" 2>/dev/null || true
    done

    # 2. Disable WiFi power-save (NetworkManager owns WiFi here via comitup).
    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/anchorpoint-wifi-powersave-off.conf <<'NMCONF'
[connection]
# 2 = disabled — keep the WiFi link awake so it doesn't nap while the Pi is idle.
wifi.powersave = 2
NMCONF
    systemctl reload NetworkManager >/dev/null 2>&1 || true
    iw dev wlan0 set power_save off >/dev/null 2>&1 || true   # best-effort immediate apply

    # 3. Let the agent restart the print stack after a failed print (self-heal),
    #    instead of needing a manual reboot. Bounded NOPASSWD grant — only these.
    cat > /etc/sudoers.d/anchorpoint-agent <<SUDO
$RUN_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart ipp-usb, /usr/bin/systemctl restart cups
SUDO
    chmod 0440 /etc/sudoers.d/anchorpoint-agent
    if ! visudo -cf /etc/sudoers.d/anchorpoint-agent >/dev/null 2>&1; then
        echo "   WARNING: sudoers grant invalid — removing it (agent self-heal will be limited)."
        rm -f /etc/sudoers.d/anchorpoint-agent
    fi
}

# Set up the brother_ql direct-USB backend for a Brother QL label printer. This
# bypasses CUPS/ipp-usb entirely (ipp-usb is unreliable with these printers — it
# wedges under load and reports false "printed"); the agent talks straight to the
# printer over USB and gets real status back. Called after pairing so config.json
# exists. Resolves the USB device automatically unless --ql-device was given.
setup_brother_ql() {
    echo "==> Setting up brother_ql direct-USB backend..."
    apt-get install -y -qq python3-pip libusb-1.0-0 >/dev/null 2>&1 || true
    python3 -m pip install --break-system-packages -q brother_ql >/dev/null 2>&1 \
        || python3 -m pip install -q brother_ql >/dev/null 2>&1 \
        || { echo "   ERROR: could not install brother_ql (pip)."; return 1; }

    # ipp-usb fights for the USB device — disable it so brother_ql/pyusb can claim it.
    systemctl disable --now ipp-usb >/dev/null 2>&1 || true

    # Let the non-root agent reach the Brother USB device without sudo.
    cat > /etc/udev/rules.d/99-brother-ql.rules <<'RULE'
# AnchorPoint: allow the agent (non-root) to talk to the Brother QL over USB.
SUBSYSTEM=="usb", ATTRS{idVendor}=="04f9", MODE="0666"
RULE
    udevadm control --reload-rules >/dev/null 2>&1 || true
    udevadm trigger >/dev/null 2>&1 || true

    # Resolve the USB device id if not supplied: usb://0x04f9:0x<product>.
    if [[ -z "$QL_DEVICE" ]]; then
        local pid
        pid="$(lsusb 2>/dev/null | grep -oiE '04f9:[0-9a-f]{4}' | head -1 | cut -d: -f2)"
        if [[ -n "$pid" ]]; then
            QL_DEVICE="usb://0x04f9:0x${pid}"
        else
            echo "   WARNING: no Brother (04f9) USB device found; pass --ql-device manually."
        fi
    fi
    echo "    model=$QL_MODEL  label=$QL_LABEL  device=${QL_DEVICE:-<unset>}"

    # Merge the backend keys into the agent config (written by the pairing step).
    QL_MODEL="$QL_MODEL" QL_LABEL="$QL_LABEL" QL_DEVICE="$QL_DEVICE" CFG="$CONFIG" \
    python3 - <<'PY'
import json, os
p = os.environ["CFG"]
c = json.load(open(p))
c.update({
    "print_backend": "brother_ql",
    "ql_model": os.environ["QL_MODEL"],
    "ql_label": os.environ["QL_LABEL"],
    "ql_device": os.environ["QL_DEVICE"],
})
json.dump(c, open(p, "w"), indent=2)
PY
    chown "$RUN_USER":"$RUN_USER" "$CONFIG" 2>/dev/null || true
}

echo "==> Installing packages (CUPS + Python requests)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends cups cups-ipp-utils python3-requests curl >/dev/null
systemctl enable --now cups >/dev/null 2>&1 || true
usermod -aG lp,lpadmin "$RUN_USER" 2>/dev/null || usermod -aG lp "$RUN_USER"

harden_print_reliability || echo "   WARNING: print-reliability hardening hit a snag (non-fatal)."

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
    USE_IPP_USB=0

    if [[ -z "$USB_URI" ]] && usb_printer_present; then
        # A USB printer is attached but there's no raw usb:// backend — modern
        # Brother / AirPrint-over-USB printers (e.g. QL-820NWB) get claimed by
        # ipp-usb, which re-exposes them as a LOCAL IPP service instead. Install
        # ipp-usb if needed and point the queue at its localhost endpoint.
        echo "    No raw usb:// device, but a USB printer is attached — using ipp-usb."
        apt-get install -y -qq ipp-usb >/dev/null 2>&1 || true
        systemctl enable --now ipp-usb >/dev/null 2>&1 || true
        IPP_PORT=""
        for _ in $(seq 1 15); do   # ipp-usb needs a moment to bind the printer's port
            IPP_PORT="$(ss -ltn 2>/dev/null | grep -oE '127\.0\.0\.1:600[0-9][0-9]' | grep -oE '600[0-9][0-9]' | sort -u | head -1 || true)"
            if [[ -n "$IPP_PORT" ]]; then break; fi
            sleep 1
        done
        IPP_PORT="${IPP_PORT:-60000}"   # ipp-usb's conventional first-printer port
        USB_URI="ipp://localhost:${IPP_PORT}/ipp/print"
        USE_IPP_USB=1
        echo "    ipp-usb endpoint: $USB_URI"
    fi

    if [[ -z "$USB_URI" ]]; then
        echo "ERROR: --printer-usb given but no USB printer found (plugged in and powered on?)."
        echo "       Devices CUPS can see:"
        lpinfo -v 2>/dev/null | sed 's/^/         /'
        exit 1
    fi

    PPD_ARG="-m everywhere"
    if [[ -n "$DRIVER_MATCH" && "$USE_IPP_USB" == "1" ]]; then
        echo "    (ignoring --driver: ipp-usb printers are driverless IPP Everywhere)"
    elif [[ -n "$DRIVER_MATCH" ]]; then
        PPD="$(lpinfo -m 2>/dev/null | grep -i -- "$DRIVER_MATCH" | head -1 | awk '{print $1}')"
        if [[ -n "$PPD" ]]; then
            PPD_ARG="-m $PPD"
            echo "    Driver: $PPD"
        else
            echo "    WARNING: no installed driver matched '$DRIVER_MATCH'; using driverless."
        fi
    fi
    echo "==> Creating CUPS queue '$QUEUE_NAME' -> $USB_URI..."
    # shellcheck disable=SC2086
    lpadmin -p "$QUEUE_NAME" -E -v "$USB_URI" $PPD_ARG
    cupsenable "$QUEUE_NAME" || true
    cupsaccept "$QUEUE_NAME" || true
    PRINTER="$QUEUE_NAME"
fi
if [[ "$BROTHER_QL" == "1" ]]; then
    :  # printing handled by the brother_ql backend, configured after pairing
elif [[ -z "$PRINTER" ]]; then
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

if [[ "$BROTHER_QL" == "1" ]]; then
    setup_brother_ql || echo "   WARNING: brother_ql setup hit a snag — set --ql-device and re-run."
fi

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
if [[ "$BROTHER_QL" == "1" ]]; then
    echo "  Print backend: brother_ql direct USB (device ${QL_DEVICE:-<unset>}, label $QL_LABEL)."
fi
if [[ "${WIFI_FALLBACK_DONE:-0}" == "1" ]]; then
    echo ""
    echo "  WiFi fallback (comitup) installed — REBOOT to activate:  sudo reboot"
    echo "  At a venue with no known WiFi the Pi makes a 'comitup-<id>' hotspot;"
    echo "  connect to it and open http://10.41.0.1 to add a network."
fi
