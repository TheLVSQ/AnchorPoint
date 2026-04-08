#!/usr/bin/env bash
# AnchorPoint droplet hardening script
# Run ONCE as root during initial server setup.
#
# BEFORE RUNNING:
#   1. Ensure you have SSH key-based login working.
#   2. Know your SSH port (default 22). Pass it as the first argument if non-standard.
#      e.g.  sudo ./harden.sh 2222
#
# What this script does:
#   - Installs and configures UFW firewall (SSH only; Cloudflare Tunnel handles web)
#   - Hardens SSH daemon (no root login, no password auth)
#   - Installs and configures fail2ban (SSH brute-force protection)
#   - Enables unattended security upgrades
#   - Locks down the .env.production file permissions
#   - Configures Docker daemon log rotation
set -euo pipefail

SSH_PORT="${1:-22}"
ENV_FILE="/opt/anchorpoint/docker/.env.production"

abort() { echo "ERROR: $*" >&2; exit 1; }
log()   { echo "[harden] $*"; }

[[ $EUID -eq 0 ]] || abort "Run as root (sudo $0)"

# ── 1. Firewall (UFW) ────────────────────────────────────────────────────────
log "Configuring UFW firewall..."
apt-get install -y -q ufw

ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# Allow SSH — do this BEFORE enabling so you don't lock yourself out
ufw allow "$SSH_PORT/tcp" comment "SSH"

# Cloudflare Tunnel handles all web traffic; no need to open 80/443.
# If you ever need direct access for debugging:
#   sudo ufw allow 8000/tcp comment "Direct web (temp)"

ufw --force enable
ufw status verbose
log "UFW enabled — only SSH ($SSH_PORT) is open inbound."

# ── 2. SSH hardening ─────────────────────────────────────────────────────────
log "Hardening SSH daemon..."
SSHD_DROP="/etc/ssh/sshd_config.d/99-anchorpoint-hardening.conf"

cat > "$SSHD_DROP" << EOF
# AnchorPoint server hardening — managed by harden.sh
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
PermitEmptyPasswords no
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

sshd -t || abort "sshd config test failed — check $SSHD_DROP before reloading"
systemctl reload sshd
log "SSH hardened. Password auth disabled, root login disabled."

# ── 3. Fail2ban ──────────────────────────────────────────────────────────────
log "Installing fail2ban..."
apt-get install -y -q fail2ban

cat > /etc/fail2ban/jail.d/anchorpoint.conf << EOF
[sshd]
enabled  = true
port     = $SSH_PORT
filter   = sshd
logpath  = /var/log/auth.log
maxretry = 5
bantime  = 3600
findtime = 600
EOF

systemctl enable --now fail2ban
systemctl restart fail2ban
log "fail2ban active — 5 bad SSH attempts = 1-hour ban."

# ── 4. Unattended security upgrades ─────────────────────────────────────────
log "Enabling unattended security upgrades..."
apt-get install -y -q unattended-upgrades

cat > /etc/apt/apt.conf.d/20auto-upgrades << EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF

unattended-upgrades --dry-run 2>/dev/null && log "Unattended upgrades configured."

# ── 5. Docker daemon: log rotation ──────────────────────────────────────────
log "Configuring Docker log rotation..."
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
systemctl reload docker 2>/dev/null || true
log "Docker log rotation set (10 MB × 3 files per container)."

# ── 6. Env file permissions ──────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    chmod 600 "$ENV_FILE"
    log ".env.production locked to owner-read-only (600)."
else
    log "Note: $ENV_FILE not found — set permissions manually after creating it."
fi

# ── 7. Disable unnecessary services ─────────────────────────────────────────
for svc in snapd avahi-daemon cups; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl disable --now "$svc" && log "Disabled: $svc"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Hardening complete. Summary:"
echo "  • Firewall: UFW on, SSH port $SSH_PORT open only"
echo "  • SSH: no root login, no password auth"
echo "  • fail2ban: protecting SSH"
echo "  • Auto security updates: enabled"
echo "  • Docker log rotation: 10 MB × 3 files"
echo ""
echo "  RECOMMENDED NEXT STEPS:"
echo "  1. Open a NEW SSH session to confirm you can still log in"
echo "     before closing your current session."
echo "  2. Add your deploy user's SSH public key to GitHub Actions"
echo "     as the DEPLOY_SSH_KEY secret."
echo "  3. Set DEPLOY_HOST, DEPLOY_USER, DEPLOY_PATH in GitHub secrets."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
