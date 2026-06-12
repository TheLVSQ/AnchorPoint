# AnchorPoint - Church Management System

## Overview

AnchorPoint is a lightweight church operations platform for small-to-mid-sized churches. It's inspired by Rock RMS but designed to be simpler, more portable, and maintainable by non-developers.

**Tech Stack:**
- Backend: Django 5.2 with Django REST Framework
- Frontend: Django templates + HTMX (minimal JavaScript)
- Database: PostgreSQL 16
- Deployment: Docker Compose with Cloudflare Tunnel

## Project Structure

```
anchorpoint/
├── anchorpoint/          # Django project config (settings, urls, wsgi)
├── core/                 # Auth, user profiles, organization settings, permissions
├── people/               # Person/contact management
├── households/           # Family groupings and relationships
├── groups/               # Volunteer teams, check-in classrooms, community groups
├── events/               # Events, registrations, attendee matching
├── checkin/              # Check-in kiosk system, label printing, print agents
├── messaging/            # SMS and phone blast communications (Twilio)
├── templates/            # Global templates
└── media/                # Uploaded files
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

## Scheduled communications & phone-blast audio

The `cron` sidecar (see `docker/docker-compose.yml` + `docker/cron.sh`) runs
`process_communications` every minute to deliver due scheduled SMS/phone blasts, and
`cleanup_audio` daily to purge old phone-blast recordings. Scheduled phone blasts need
`SITE_BASE_URL` (or Organization Settings > Website) so the headless worker can build
absolute audio + Twilio status-callback URLs. Phone-blast audio (uploaded or recorded
in-browser via `MediaRecorder`) is transcoded to MP3 with `ffmpeg` so Twilio's `<Play>`
can fetch it.

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
docker compose exec web python manage.py setup_beta_users
```

## Testing

Run tests with:
```bash
python manage.py test
```

Key test files:
- `events/tests.py` - Most comprehensive, covers registration matching
- `people/tests.py` - Basic CRUD tests
- `core/tests.py` - Auth tests

## Recent Changes (Session Context)

Last session focused on:
1. Fixed IDOR vulnerability in release document deletion
2. Fixed SECRET_KEY security (removed fallback)
3. Added `normalized_phone` field for O(1) phone lookups
4. Created centralized permission system with decorators
5. Production Docker setup (gunicorn, whitenoise, health checks)
6. Cloudflare Tunnel configuration support
7. Fixed phone blast audio URL for Twilio (needs absolute URL)
8. Created `setup_beta_users` management command

## TODO — Family/People UX (queued 2026-06-12, from VBS testing)

- [x] **Person form: "Join an existing family"** — fixed: hx-boost killed the DOMContentLoaded toggle script; selection now validated server-side.
- [x] **Family management UI** — shipped: /families/ list/detail/edit + member ops.
  Original note: **Family management UI** — list/view/edit all households. Direction to evaluate: a dedicated Families page under People (households are already their own model; surfacing them as a Group type conflates two concepts), plus household section on each person's profile. Edit = rename, add/remove members, change roles/primary adult.
- [ ] **Nightly family-hygiene job (2-3am via cron sidecar)** — detect orphaned households (0 members or no adults) and likely duplicates (same normalized phone/address/last name); write findings to a review queue where admins can merge/edit/delete. Merge needs care: re-point HouseholdMembers, check-ins, event registrations.
- [x] **Person status displays raw value** — fixed (get_status_display).
  Original note: **Person status displays raw value** — "regular_attendee" with underscores; templates should use `get_status_display`.
- [ ] **Address verification on person add** — evaluate: USPS Web Tools API (free, US-only) vs Smarty/Lob (paid, easier). Likely pattern: normalize + autocomplete-on-blur, store verified flag; degrade gracefully when API not configured.
- [x] **People page tile view** — shipped: age + family link + status chip, prefetched; pagination already existed.
  Original note: **People page tile view** — show age, family/household name, status chip alongside name/email. At scale: server-side pagination (~50/page) + the existing search as primary navigation; consider an A-Z last-name filter rail.

## Pending operational follow-ups

- [ ] Run on the print Pi: `sudo lpadmin -p ChurchLabel -o CutMedia-default=EndOfPage`, then a Test Print to verify label cutting (waiting on label stock).
- [ ] Import the real VBS signup CSV when it arrives (`import_signups`, dry-run → review → `--commit --group "VBS 2026"`).

## TODO (Medium Priority)

- [ ] Add `select_related`/`prefetch_related` to dashboard queries
- [ ] Extract duplicate recipient query logic in messaging forms
- [ ] Refactor fat views into service layer
- [ ] Add database indexes (Event.slug, Event.registration_token, Person.email)
- [ ] Add tests for messaging services
- [ ] Implement proper pagination
- [ ] Create service layers for people, households, groups modules

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
