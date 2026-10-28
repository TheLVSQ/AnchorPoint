# AnchorPoint - Church Management System

## Overview

AnchorPoint is a lightweight church operations platform for small-to-mid-sized churches. It's inspired by Rock RMS but designed to be simpler, more portable, and maintainable by non-developers.

**Tech Stack:**
- Backend: Django 5.2 (DRF is pinned in requirements but not wired up; no API on main yet, see `TODO.md`)
- Frontend: Django templates + HTMX (minimal JavaScript)
- Database: PostgreSQL 16
- Deployment: Docker Compose with Cloudflare Tunnel on a DigitalOcean droplet. Deploys run through the manual `Deploy to Production` GitHub Action (`.github/workflows/deploy.yml`).

**Backlog lives in `TODO.md`, with bigger work as GitHub Issues** (see *Agent skills*). This file is reference only.

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

### Person identity (`people/services/identity.py`)

Every intake path (public registration, staff match queue, signup + Rock imports, kiosk
add-child) asks `identity.find_person(Incoming(...), family=...)` "is this someone we have?".
Order: external id → email → name + birthdate → phone → same name inside `family`. Every step
after external id **requires the first name to agree** (families share emails and phones); a
different birthdate rules a candidate out; two or more candidates = no match (staff queue).
Phones compare on the last 10 digits (`identity.same_phone`). Matched data goes in through
`identity.absorb()`: blank fields filled, safety text (allergies, custody, pickup, notes)
added to, never dropped. Merge uses the same rule. Unmatched attendees go to the manual queue;
auto-matches record why in `match_notes`. Kiosk quick-register never matches (self-service).
People → Duplicates shows the nightly cleanup's duplicate pairs (read-only; admins merge).

### Phone Number Normalization (`people/models.py`)

The `Person.normalized_phone` field stores digits-only version for fast lookups. Auto-populated on save via `normalize_phone()` function. Indexed for O(1) queries instead of O(n) iteration.

### Outbound communications (`messaging/outbound.py`)

Every text / phone blast to people in the directory goes through this one module
(terms in `GLOSSARY.md`): a **Communication** with one **Delivery** per recipient.

- **Broadcasts** (staff-written): `check_broadcast()` (forms) → `broadcast()` queues it →
  `dispatch_due()` (cron, every minute) sends it. "Send now" = within a minute. Opt-in is
  re-checked at send time (opted-out → Delivery `skipped`/`opted_out`); a due broadcast
  inside the blackout window waits until it ends.
- **Transactional** (event-triggered, e.g. check-in pickup code): `send_transactional()`
  sends immediately, obeys opt-in, ignores blackout; records nothing if Twilio isn't set up.
- **Adapters** (`messaging/adapters.py`): `settings.OUTBOUND_ADAPTERS` maps channel →
  `TwilioSms` / `TwilioVoice`; under tests every channel is `FakeAdapter` (call
  `FakeAdapter.reset()` in setUp; set `is_ready` / `fail_with` to simulate). Email = a new
  adapter + consent field.
- The Delivery is the audit trail (person page "Communications History" reads Deliveries).
- Staff operational alerts (family flags, health email, welcome/registration emails) are
  *not* Communications; they use `messaging/twilio_client.py` / `send_mail` directly.
- Phone blasts need absolute audio + status-callback URLs (`SITE_BASE_URL`); the webhook
  verifies Twilio's signature against that registered public URL (behind Cloudflare Tunnel
  the request arrives on an internal http host) and calls `record_call_status()`. A call with
  no callback after 2h is settled as failed "No status received" by `dispatch_due()`.

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
- `python manage.py trigger_site_rebuild` - Rebuild the church website if the public events feed changed (run by the cron sidecar; no-op without `WEBSITE_DEPLOY_HOOK_URL`). See *Church website feed* below.
- `python manage.py import_signups <csv|-> [--commit] [--group "VBS 2026"]` - Bulk-import families (one CSV row per child; see `docs/signup-import-template.csv`). Dry-run by default; matches existing people via `people/services/identity.py` (parents by name + email/phone, kids by name within the parent's family) so re-imports never duplicate. `--group` enrolls imported children for check-in eligibility filtering.

## Known Limitations

1. **No SMS delivery webhooks** - Phone calls update status via Twilio StatusCallback, but SMS delivery status is not tracked after the initial send
2. **Media files served by Django** - OK for small scale, use nginx/CDN for larger deployments

## Check-in states (`checkin/models.py`)

A `CheckIn` is always in one of four states (terms in `GLOSSARY.md`): **Expected** (pre-staged via
the session Pre-print page, label printed ahead), **No-show** (expected, confirmed absent;
reversible), **Present** (arrived, not checked out), **Checked out**. **Active** = not checked out
(holds the live pickup code); **Attended** = arrived at some point. The state is derived from
`arrived_at` / `checked_out_at` / `no_show`, never stored.

**Never write those filters by hand.** Ask the model: `session.checkins.present()` (and
`.expected()`, `.no_show()`, `.checked_out()`, `.active()`, `.attended()`, `.state_counts()`),
`CheckIn.state_q(state)` / `CheckIn.attended_q()` for annotations, `checkin.state` for one row.
Change state only through the transitions (`arrive(user)`, `mark_no_show()`, `check_out(user)`,
on a row or a queryset): each only touches rows in a valid starting state and returns what
changed. `checked_in_by` is the staff member who confirmed arrival (blank for kiosk self
check-in).

**Checking a family in** goes through `checkin/services/family_checkin.py`, never the views:
`check_in_family()` (kiosk: pre-staged arrive with their printed code and no reprint; walk-ins get
ONE fresh code per submission, never the family's live code; room = chosen or age/grade-matched;
then labels, one pickup-code text per code, auto-enroll, family-safety alert), `stage_families()`
(Pre-print: Expected rows with the family's code), `confirm_arrivals()` (manager "mark arrived":
records staff + safety alert), `print_labels()` (the only way to print; one pickup tag per code).
Side effects never block check-in. Terms (pickup code, walk-in, pre-staged) are in `GLOSSARY.md`.

## Scheduled communications & phone-blast audio

The `cron` sidecar (see `docker/docker-compose.yml` + `docker/cron.sh`) runs
`process_communications` every minute to send due broadcasts (`outbound.dispatch_due`), and
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
- **Picking a person:** never a `<select>` of the whole directory. Hide the form's `person` field and
  add a search box that `hx-get`s `person_pick` (`people/views.py`) into a div inside the form; it
  returns `name="person"` radios. Keep Enter in the search box from submitting the form. Examples:
  `events/manage/registration_queue.html`, `messaging/sms_form.html`.
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

## Church website feed (`events/feeds.py`)

The public website (separate repo `bolivar-community-church-site`, Astro on Cloudflare) renders
its own event list and detail pages from **`/events/feed.json`** at build time;
**`/events/feed.ics`** is the subscribable calendar (the site re-serves it from its own domain).
Both are public, read-only, cached 5 min, and carry what a public event page shows (published events
with an upcoming occurrence: description, location, dates, photos, cost). Never add contact,
capacity, registration counts or release documents; `events/test_feeds.py` asserts they stay out.
`registration_url` (contains the registration token) is present only while registration is open,
same as the public page's Register link.

**`WEBSITE_URL`** (e.g. `https://bolivar.church`) makes the website the public face: feed/ICS event
links point there, `/events/` and `/events/<slug>/` redirect there, and the sign-up form at
`/register/<token>/?embed=1` renders frameless (`events/public/embed_base.html`, website palette in
`app.css` under `body.embed`) with `frame-ancestors <WEBSITE_URL origin>` instead of
`X-Frame-Options: DENY`. The embed posts its height to the parent (`anchorpoint:height` /
`anchorpoint:loaded` postMessages). Embedding needs the website on a `*.bolivar.church` host:
the CSRF cookie is `SameSite=Lax`, so a cross-site frame (e.g. `workers.dev`) can't submit.

`trigger_site_rebuild` (cron sidecar, every minute) hashes the feed payload and POSTs
`WEBSITE_DEPLOY_HOOK_URL` (a Cloudflare Workers Builds deploy hook; secret) when it changes,
at most once per 5 min. State lives in the one-row `WebsiteRebuildState`. Unset hook = no-op.

## Reporting (`reporting/` app)

A small report **registry**: subclass `reporting.reports.Report` (declare `slug`, `name`,
`columns()`, `get_rows(params)`, optional `param_form_class`) and `@register` it — the generic
list/detail/CSV-export views at `/reports/` pick it up with no new URLs. Ships with
`GroupRosterReport` (VBS-style roster by group) and `SessionAttendanceReport`. CSV only for now.

`Person.photo_consent` = guardian permission to photograph a minor / use their image: one of
`unknown` (default), `granted`, `denied`. Captured on the person form, kiosk quick-register and
add-child (ticked = granted, else unknown), and `import_signups` (a `photo_consent` column: set on
new kids, and filled on matched kids only while still `unknown`; never overwrites an explicit
choice). Shown on the profile and in reports.

## Family membership (`households/membership.py`)

Every in-app membership change goes through this module, never `HouseholdMember.objects` directly:
`add_member(household, person, role)` (role required: no silent "adult"), `remove_member`,
`move_member` (move or copy), `set_role`, `set_primary` (refuses non-adults), `create_family`
("{Surname} Family"), `link_guardian` (registration + staff queue; raises a family-safety flag when
the child is already in another family, `raise_flag=False` for bulk imports), `family_surname`.
The **primary adult is always an adult member or blank**: it hands over to the longest-standing
adult when the primary leaves or is demoted. Families with no adult are allowed (nightly cleanup
flags them). Rock re-imports treat Rock's age-derived role as authoritative.
`scripts/fix_primary_adults.py` reports/fixes old families that break the rule.

## Data cleanup (`households/hygiene.py`, `/families/cleanup/`)

Nightly (cron sidecar, 07:00 UTC) `manage.py family_hygiene` finds likely duplicate people,
likely duplicate families, empty families, and families with no adult, and syncs them into
`CleanupFinding` (stable `key` per pair: dismissed stays dismissed, no-longer-matching
auto-resolves, re-matching reopens). Admin-only page with merge (pick which record to keep),
delete-empty-family, dismiss, reopen; re-runs detection after each action. Rules are
conservative (first name must match; differing birthdates veto; a shared child is never a
family-duplicate signal; different `external_id`s never pair). `--dry-run` prints counts only.
Merges go through `people/services/merge.py`: safety text (allergies, custody, pickup, notes)
is combined, not dropped, and merging two people who both have logins is blocked.

## Help guides (`helpcenter/` app, `/help/`)

User-facing how-to guides, linked from the sidebar footer for every logged-in user. Each guide
is a Markdown file in `anchorpoint/helpcenter/guides/<slug>.md`, registered in `GUIDES`
(`helpcenter/guides.py`). Images use relative paths (`![Alt](checkin-setup/01-rooms.png)`) that
resolve to `helpcenter/static/help/`; a test fails if one is missing (it would 500 in prod under
the hashed static storage). "Print / save PDF" uses print styles in `app.css`.

Screenshots come from `scripts/help_screenshots.py`: it seeds a **throwaway `*_docs` DB** with
fictional families (repo is public — never real data), drives your installed Chrome via
Playwright (docs-only dependency, not in requirements), and can write the guide as a PDF.
See its docstring for the one-time DB container + `LABEL_FONT_DIR` (DejaVu fonts for the
sample labels). Re-run it when check-in screens change.

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
from messaging import outbound
from messaging.models import Communication

# Event-triggered text, sent now (opt-in enforced, blackout ignored):
outbound.send_transactional(Communication.Channel.SMS, people=[person], body="...", title="...")

# Staff broadcast, sent by the scheduler (raises outbound.BroadcastRejected on problems):
outbound.broadcast(Communication.Channel.SMS, created_by=user, group=group, body="...")
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

Baseline (2026-10-19): 628 Django tests + 22 agent tests, all passing. `checkin` has the most
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

## Agent skills

### Issue tracker

Small items in `TODO.md`; bigger work as GitHub Issues with a TODO.md pointer. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
