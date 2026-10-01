#!/bin/sh
# Host maintenance status for AnchorPoint's daily health email.
#
# Runs on the DROPLET (root cron; setup steps in CLAUDE.md "Maintenance alerts"),
# not in a container: containers can't see reboot-required, apt state, or the
# root-only backup dir. Writes a small JSON file that the cron container
# mounts read-only at /hoststatus/status.json; `manage.py system_health`
# reads it. Reporting only — changes nothing.
set -eu

OUT_DIR="${OUT_DIR:-/var/lib/anchorpoint-host}"
BACKUP_DIR="${BACKUP_DIR:-/home/deploy/anchorpoint/docker/backups}"
mkdir -p "$OUT_DIR"
chmod 755 "$OUT_DIR"

now=$(date +%s)

reboot_required=false
reboot_since=0
if [ -f /var/run/reboot-required ]; then
    reboot_required=true
    reboot_since=$(stat -c %Y /var/run/reboot-required)
fi

updates=0
security=0
if [ -x /usr/lib/update-notifier/apt-check ]; then
    counts=$(/usr/lib/update-notifier/apt-check 2>&1 || true)   # "N;M"
    updates=${counts%%;*}
    security=${counts##*;}
fi
case "$updates" in ''|*[!0-9]*) updates=0 ;; esac
case "$security" in ''|*[!0-9]*) security=0 ;; esac

disk_pct=$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')
disk_free_gb=$(df -P -BG / | awk 'NR==2 {gsub("G","",$4); print $4}')

latest_backup=0
newest=$(ls -1t "$BACKUP_DIR"/anchorpoint-*.sql.gz 2>/dev/null | head -1 || true)
[ -n "$newest" ] && latest_backup=$(stat -c %Y "$newest")
latest_backup_bytes=0
[ -n "$newest" ] && latest_backup_bytes=$(stat -c %s "$newest")

uptime_days=$(awk '{print int($1/86400)}' /proc/uptime)

tmp="$OUT_DIR/status.json.tmp"
cat > "$tmp" <<JSON
{
  "generated_at": $now,
  "reboot_required": $reboot_required,
  "reboot_required_since": $reboot_since,
  "updates_pending": $updates,
  "security_updates_pending": $security,
  "disk_used_pct": ${disk_pct:-0},
  "disk_free_gb": ${disk_free_gb:-0},
  "latest_backup_at": $latest_backup,
  "latest_backup_bytes": $latest_backup_bytes,
  "uptime_days": $uptime_days
}
JSON
chmod 644 "$tmp"
mv "$tmp" "$OUT_DIR/status.json"
