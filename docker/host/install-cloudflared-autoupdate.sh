#!/bin/sh
# One-time (idempotent) droplet setup: keep cloudflared patched automatically.
#
#   sudo sh docker/host/install-cloudflared-autoupdate.sh
#
# Adds Cloudflare's apt repo to unattended-upgrades (daily, ~06:00 UTC) and a
# dpkg hook that restarts the tunnel when the binary changes (a few seconds of
# downtime for anchorpoint.bolivar.church, overnight US time).
set -eu
here=$(cd "$(dirname "$0")" && pwd)

install -m 644 "$here/52unattended-cloudflared" /etc/apt/apt.conf.d/52unattended-cloudflared
install -m 755 "$here/cloudflared-restart-if-updated" /usr/local/sbin/cloudflared-restart-if-updated

# Show what unattended-upgrades will now consider (cloudflared should be listed
# if an update is pending; otherwise the origin line confirms it's allowed).
apt-config dump | grep -A2 "Unattended-Upgrade::Origins-Pattern" || true
echo "cloudflared auto-update installed."
