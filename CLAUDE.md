# AnchorPoint - Church Management System

## Overview

AnchorPoint is a lightweight church operations platform for small-to-mid-sized churches. It's inspired by Rock RMS but designed to be simpler, more portable, and maintainable by non-developers.

**Tech Stack:**
- Backend: Django 5.2 (DRF is pinned in requirements but not wired up; no API on main yet, see `TODO.md`)
- Frontend: Django templates + HTMX (minimal JavaScript)
- Database: PostgreSQL 16
- Deployment: Docker Compose with Cloudflare Tunnel on a DigitalOcean droplet. Deploys run through the manual `Deploy to Production` GitHub Action (`.github/workflows/deploy.yml`).

**Backlog lives in `TODO.md`.** This file is reference only.

## Project Structure

```
anchorpoint/              # Django project root (manage.py, .env)
├── anchorpoint/          # Django project config (settings, urls, wsgi)
├── core/                 # Auth, user profiles, organization settings, permissions
├── people/               # Person/contact management, merge service
├── households/           # Family groupings and relationships (/families/)
├── groups/               # Volunteer teams, check-in classrooms, community groups
├── events/               # Events, registrations, attendee matching
├── checkin/              # Check-in kiosk system, label printing, print agents
├── messaging/            # SMS and phone blast communications (Twilio)
├── reporting/            # Report registry + CSV export
├── templates/            # Global templates
└── media/                # Uploaded files
agent/                    # Raspberry Pi print agent (standalone, own tests)
docker/                   # Production Dockerfile, compose, cron, backups
scripts/                  # dev-setup.sh, load test, VBS CSV transform
```

## Key Design Decisions

### Permission System (`core/permissions.py`)

Centralized decorators for consistent authorization:
- `@admin_required` - Admin-only views (settings, role management)
- `@staff_required` - Staff+ views (people, groups, events, attendance)
- `@communications_required` - SMS/phone blast access

Role hierarchy: Admin > Staff > Volunteer Admin > Volunteer

### Person Matching (`events/services.py`)

When registrations come in, the system attempts to match attendees to existing Person records:
1. Email match (case-insensitive)
2. Name + birthdate match
3. Normalized phone match (uses indexed `normalized_phone` field)

Unmatched attendees go to a queue for manual review.

### Phone Number Normalization (`people/models.py`)

The `Person.normalized_phone` field stores digits-only version for fast lookups. Auto-populated on save via `normalize_phone()` function. Indexed for O(1) queries instead of O(n) iteration.

### Twilio Integration (`messaging/services.py`)

- `TwilioService` class handles SMS and voice calls
- Phone blasts require absolute URLs for audio files (Twilio fetches them)
- Blackout windows prevent sends during configured quiet hours
- All communications logged to `CommunicationLog` for audit trail

## Environment Configuration

Key environment variables (see `.env.production.example`):
- `SECRET_KEY` - Required, no fallback
- `DEBUG` - Defaults to False
- `ALLOWED_HOSTS` - Comma-separated list
- `CSRF_TRUSTED_ORIGINS` - Full URLs with https://
- `DB_*` - PostgreSQL connection settings

## Management Commands

- `python manage.py create_admin --username <u> --email <e> [--password <p>] [--name "First Last"]` - Create or promote a user to admin (staff + superuser + ADMIN role). Idempotent; generates a password if none given. **Preferred way to bootstrap an admin after deployment.**
- `python manage.py rotate_passwords <username...>` (or `--all-staff`) - Reset the given users' passwords to fresh random values and print them once. Use after a credential exposure or lockout.
- `python manage.py setup_beta_users` - (Legacy) Creates admin + 2 staff testers with random passwords. Superseded by `create_admin` for new deployments.
- `python manage.py import_signups <csv|-> [--commit] [--group "VBS 2026"]` - Bulk-import families (one CSV row per child; see `docs/signup-import-template.csv`). Dry-run by default; matches existing people via the events-app matching service so re-imports never duplicate. `--group` enrolls imported children for check-in eligibility filtering.

## Known Limitations

1. **No SMS delivery webhooks** - Phone calls update status via Twilio StatusCallback, but SMS delivery status is not tracked after the initial send
2. **Media files served by Django** - OK for small scale, use nginx/CDN for larger deployments

## Check-in states (`CheckIn.arrived_at`)

A `CheckIn` has three states: **expected** (pre-staged via the session Pre-print page —
label printed ahead, `arrived_at IS NULL`), **present** (`arrived_at` set, not checked out),
**checked out**. "Currently here" / room-occupancy / checkout all mean *present*
(`arrived_at__isnull=False, checked_out_at__isnull=True`). Normal kiosk check-ins set
`arrived_at` at creation; pre-staged ones get it on the one-tap kiosk arrival (no reprint —
the label/code were printed ahead). Pre-print pre-assigns rooms and shares one pickup code
per household.

## Scheduled communications & phone-blast audio

The `cron` sidecar (see `docker/docker-compose.yml` + `docker/cron.sh`) runs
`process_communications` every minute to deliver due scheduled SMS/phone blasts, and
`cleanup_audio` + `purge_print_images` daily (old phone-blast recordings; label PNGs
from print jobs older than 24h — finished jobs are already cleared on ack). Scheduled phone blasts need
`SITE_BASE_URL` (or Organization Settings > Website) so the headless worker can build
absolute audio + Twilio status-callback URLs. Phone-blast audio (uploaded or recorded
in-browser via `MediaRecorder`) is transcoded to MP3 with `ffmpeg` so Twilio's `<Play>`
can fetch it.

## UI / design system ("Harbor")

- All app styling lives in `anchorpoint/static/css/app.css` (tokens at the top: colors for light +
  dark via `prefers-color-scheme`, radius, shadows, `--font` = Figtree, `--font-heading`).
  `templates/base.html` is just the shell: navy sidebar on desktop (≥1024px), drawer on phones,
  public top bar when logged out. **Don't add new inline `style=""` or per-template `<style>`** —
  add a class to `app.css` using the tokens. (Inline-style count is the sweep's progress metric.)
- Sidebar links are role-aware via the `nav` context (`core/context_processors.py`): only show
  pages the user can open. Active section = longest URL-prefix match in `_NAV_SECTIONS`.
- Patterns: `.page-header` (stacked) / `.page-header--split` (title left, actions right),
  `.btn` / `.btn.ghost` / `.btn.danger` / `.btn-sm`, `.card`, `.data-table` (wrap in `.table-wrap`),
  `.chip` (+ `--warning/--danger/--success/--neutral`), `.empty-state`, `.message.<tag>`.
- Static files use `STORAGES` (hashed + gzipped by whitenoise in prod; plain in tests/DEBUG).
  The kiosk (`checkin/kiosk/base.html`), labels, and emails have their own styling — out of scope.

## Maintenance alerts

- **Daily health email** — `manage.py system_health` (cron sidecar, daily) checks disk %, backup
  age/size, droplet reboot-needed and pending security updates, print agents silent >7 days, and
  failed SMS/phone blasts in the last 24h. Emails **Settings → Organization → Maintenance Alerts**
  recipients only when something's wrong, plus an all-clear every Monday. `--force-email` to test.
- **Host status** — containers can't see apt/reboot state or the root-only backups, so
  `docker/hoststatus.sh` runs on the droplet via root cron (`/etc/cron.d/anchorpoint-hoststatus`,
  every 30 min) and writes `/var/lib/anchorpoint-host/status.json`, mounted read-only into the cron
  container at `/hoststatus`. Reinstall after editing the script:
  `sudo install -m 755 docker/hoststatus.sh /usr/local/sbin/anchorpoint-hoststatus`.
- **Weekly security reboot** — unattended-upgrades installs security updates daily; root cron
  (`/etc/cron.d/anchorpoint-reboot`) reboots **Tuesdays 07:30 UTC (~3:30am ET) only if
  `/var/run/reboot-required` exists**. Containers come back via `restart: unless-stopped`.
- **Storage** — deploys prune unused images/build cache older than a week; container logs are
  capped (10MB × 3 per service); backups keep 14 days; `cleanup_audio` purges finished
  phone-blast audio after 30 days (`AUDIO_RETENTION_DAYS`).
- **Dependencies** — Dependabot alerts + weekly PRs (`.github/dependabot.yml`).

## Reporting (`reporting/` app)

A small report **registry**: subclass `reporting.reports.Report` (declare `slug`, `name`,
`columns()`, `get_rows(params)`, optional `param_form_class`) and `@register` it — the generic
list/detail/CSV-export views at `/reports/` pick it up with no new URLs. Ships with
`GroupRosterReport` (VBS-style roster by group) and `SessionAttendanceReport`. CSV only for now.

`Person.photo_consent` (default False) = guardian opt-in to photographing a minor / using their
image. Captured on the person form, kiosk quick-register, and `import_signups` (a `photo_consent`
column, set on create only); shown on the profile and in reports.

## Common Tasks

### Adding a new permission-protected view
```python
from core.permissions import staff_required

@staff_required
def my_view(request):
    ...
```

### Querying people by phone
```python
from people.models import Person, normalize_phone

phone_digits = normalize_phone("+1 (555) 123-4567")  # Returns "15551234567"
person = Person.objects.filter(normalized_phone=phone_digits).first()
```

### Sending SMS programmatically
```python
from messaging.services import TwilioService, deliver_sms_message
from messaging.models import SmsMessage, SmsRecipient

# Create message and recipients, then:
deliver_sms_message(sms_message)
```

## Deployment

See `DEPLOY.md` for full Cloudflare Tunnel deployment guide.

Quick start:
```bash
cd docker
cp ../.env.production.example ../.env.production
# Edit .env.production with your values
docker compose build
docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py create_admin --username <u> --email <e>
```

(Migrations also run automatically on container start via `docker/entrypoint.sh`.)

## Local dev & testing

One idempotent script sets everything up: Postgres 16 in OrbStack/Docker on **localhost:5433**
(container `anchorpoint-dev-db`), a Python 3.12 `.venv/` at the repo root, and `anchorpoint/.env`
(it's written only if missing).

```bash
scripts/dev-setup.sh          # set up / start everything
scripts/dev-setup.sh test     # ...and run the Django + print-agent test suites
```

Manual equivalents, from `anchorpoint/`:
- `../.venv/bin/python manage.py test`
- `cd ../agent && ../.venv/bin/python -m unittest test_agent`

Baseline (2026-10-01): 516 Django tests + 22 agent tests, all passing. `checkin` has the most
coverage (~195 tests); `events/tests.py` covers registration matching.

Prod shell (once SSH'd into the droplet):
`cd /home/deploy/anchorpoint/docker && docker compose exec -T web python manage.py shell`.

## Production config status (checked on prod 2026-10-01)

- [x] **Kiosk PIN** is set (Settings → Organization).
- [x] **Backups**: the backup sidecar writes a daily `pg_dump` to `docker/backups/` on the droplet (~88 MB gzipped).
- [x] **Brother agent** ("Pi Print Monitor 1", host `bcc-print-pi-1`): 62mm width, 90° rotation (prints the landscape label ~62×93mm).
- **Zebra ZD500**: retired (printer recycled, Oct 2026). The Brother is the only printer in use. The "Printer 2: Zebra ZD500" agent record on prod is now unused.

## Label rendering

Labels render as a canonical **76×51mm (3"×2") landscape** design (`label_generator.LABEL_WIDTH=898`).
Each print agent has a `label_rotation`: print as-is on a wide die-cut label, or rotate 90°/270° to
stand it up on a narrow continuous roll (flip 90↔270 if it feeds upside down). The agent
passes `-o CutMedia=EndOfPage` per job on queues that expose CutMedia. `install.sh` also sets
`CutMedia-default=EndOfPage` as a backup.

## Print agent backends — CUPS vs brother_ql (Brother QL printers)

The Pi print agent (`agent/anchorpoint_agent.py`) has two print backends, chosen by
`print_backend` in its `config.json`:

- **`cups`** (default) — prints via `lp` to a CUPS queue. Fine for network/driverless
  printers. For a **USB Brother QL** it goes through **ipp-usb**, which is unreliable:
  under check-in load it wedges and reports false `printed` (CUPS says done, no ink) —
  the "labels don't print until I reboot the Pi" symptom. Self-heal + offline-agent
  fallback mitigate but don't fully fix it (CUPS can't see ipp-usb's lie).
- **`brother_ql`** (recommended for Brother QL) — talks **straight to the printer over
  USB** via the `brother_ql` lib, no CUPS/ipp-usb. The send is blocking and returns the
  printer's **real** status, so failures are accurate and there's nothing to wedge.
  Validated reliable on a QL-820NWB where ipp-usb failed ~half the time.

**Set it up (fresh install):** add `--brother-ql` to the install one-liner —
`curl -fsSL <host>/checkin/agent/install.sh | sudo bash -s -- --server <host> --code XXXX --brother-ql`.
That installs `brother_ql`+libusb, **masks** `ipp-usb`, adds a udev rule so the non-root
agent can reach the USB device (vendor `04f9`, `MODE=0666`), auto-detects the device, and
writes the config. Optional: `--ql-device usb://0x04f9:0xNNNN`, `--ql-label 62`,
`--ql-model QL-820NWB`.

**Why `mask`, not `disable`:** `ipp-usb` is udev/socket-activated, so `systemctl disable`
does **not** survive a reboot/replug — udev restarts it and it re-grabs the USB device,
and `brother_ql` then fails with `[Errno 16] Resource busy` (every label fails until the
Pi is touched). `systemctl mask --now ipp-usb` blocks every activation path. To recover a
Pi already stuck this way: `sudo systemctl mask --now ipp-usb && sudo systemctl restart anchorpoint-agent`.

**Switch an already-running Pi:** re-pull the agent, then set config keys
`print_backend=brother_ql`, `ql_model`, `ql_label` (`62` = 62mm continuous), `ql_device`
(`usb://0x04f9:0x<pid>` from `lsusb`), add the udev rule, `systemctl mask --now ipp-usb`,
restart the service. Agent code: `_print_brother_ql` (fits the PNG to the label's printable
width, `convert` + blocking `send`). `brother_ql`/PIL are imported lazily so cups-mode
agents don't need them.
