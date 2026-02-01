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
├── attendance/           # Check-in kiosk system
├── messaging/            # SMS and phone blast communications (Twilio)
├── registrations/        # (Scaffolded, minimal implementation)
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

- `python manage.py setup_beta_users` - Creates admin + 2 staff testers with random passwords

## Known Limitations

1. **Scheduled messages** - Marked as scheduled but no background job to send them
2. **No Twilio webhooks** - Delivery status not updated after initial send
3. **Media files served by Django** - OK for small scale, use nginx/CDN for larger deployments

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

## TODO (Medium Priority)

- [ ] Add `select_related`/`prefetch_related` to dashboard queries
- [ ] Extract duplicate recipient query logic in messaging forms
- [ ] Refactor fat views into service layer
- [ ] Add database indexes (Event.slug, Event.registration_token, Person.email)
- [ ] Add tests for messaging services
- [ ] Implement proper pagination
- [ ] Create service layers for people, households, groups modules
