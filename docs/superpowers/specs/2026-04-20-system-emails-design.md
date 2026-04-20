# System Emails Design

**Date:** 2026-04-20
**Status:** Approved

## Overview

Add system email capability to AnchorPoint — automated, event-driven notifications with auto-generated content sent to users when something happens in the system. This is distinct from newsletter/communication emails (future feature), which will be user-authored content blasted to a recipient list.

---

## Scope

Four system emails:

1. **Password reset** — triggered by Django's built-in auth flow
2. **Welcome email** — sent to a new user when their account is created
3. **Registration confirmation** — sent to a registrant after successfully registering for an event
4. **Staff new registration notification** — sent to all admin/staff users when a new event registration comes in

---

## Backend: Google Workspace SMTP

Django's built-in `EmailBackend` is used — no additional packages required. Credentials are stored in `.env.production` (not in the database), consistent with how other secrets (`SECRET_KEY`, Twilio credentials) are handled.

### Environment Variables

Added to `.env.production` and `.env.production.example`:

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=info@bolivar.church
EMAIL_HOST_PASSWORD=<google-app-password>
DEFAULT_FROM_EMAIL=AnchorPoint <info@bolivar.church>
```

To generate the app password: Google Account → Security → 2-Step Verification → App passwords. Create one named "AnchorPoint".

### Django Settings

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'info@bolivar.church')
```

---

## Service Layer

A new file `core/email_service.py` holds all sending functions. This follows the same pattern as `messaging/services.py` for Twilio — a clean service layer that views and signals call into.

### Functions

```python
def send_welcome_email(user: User) -> None
def send_registration_confirmation(registration: EventRegistration) -> None
def send_staff_registration_notification(registration: EventRegistration) -> None
```

Password reset has no service function — Django's `django.contrib.auth` views handle it automatically once the email backend is configured.

### Error Handling

All functions catch and log email exceptions but never re-raise them. A failed email must never break the user-facing action that triggered it (e.g., a failed confirmation email must not roll back a registration).

---

## Triggers

| Email | Trigger point | Recipient(s) |
|---|---|---|
| Password reset | Django built-in — no code needed | User who requested reset |
| Welcome | `post_save` signal on `User` (created=True) in `core/models.py` | The new user |
| Registration confirmation | After successful save in `events/views.py` registration handler | Registrant's email from the registration form |
| Staff notification | Same point as registration confirmation | All `UserProfile` with `role` in `['admin', 'staff']` |

**Staff recipient query:**
```python
UserProfile.objects.filter(
    role__in=[UserProfile.Role.ADMIN, UserProfile.Role.STAFF]
).select_related('user')
```

Staff recipients are dynamic — adding or removing staff in the system automatically affects who receives notifications, no additional config needed.

---

## Templates

Each email has an HTML version and a plain text fallback. Templates live in `templates/emails/` and extend a shared base template.

```
templates/emails/
├── base.html                          # Shared header/footer with org name
├── welcome.html
├── welcome.txt
├── registration_confirmation.html
├── registration_confirmation.txt
├── staff_new_registration.html
└── staff_new_registration.txt

templates/registration/
├── password_reset_email.html          # Overrides Django default
└── password_reset_subject.txt        # Overrides Django default
```

The base template pulls the church name from `OrganizationSettings` via the existing `organization_settings` context processor, so emails are branded automatically without additional configuration.

### Template Context

| Template | Context variables |
|---|---|
| `welcome` | `user`, `org` |
| `registration_confirmation` | `registration`, `event`, `org` |
| `staff_new_registration` | `registration`, `event`, `org` |
| `password_reset_email` | Django standard: `user`, `uid`, `token`, `domain`, `protocol` |

---

## Files Changed

| File | Change |
|---|---|
| `anchorpoint/anchorpoint/settings.py` | Add SMTP email backend config |
| `.env.production.example` | Add email environment variable examples |
| `core/email_service.py` | New — sending functions |
| `core/models.py` | Add `post_save` signal handler for welcome email |
| `events/views.py` | Call confirmation + staff notification after registration |
| `templates/emails/base.html` | New — shared email base |
| `templates/emails/welcome.html` + `.txt` | New |
| `templates/emails/registration_confirmation.html` + `.txt` | New |
| `templates/emails/staff_new_registration.html` + `.txt` | New |
| `templates/registration/password_reset_email.html` | New — overrides Django default |
| `templates/registration/password_reset_subject.txt` | New — overrides Django default |

---

## Out of Scope

- Newsletter / communication emails (user-authored content blasted to a list) — future feature
- Email delivery tracking / bounce handling
- Unsubscribe management
- Scheduled emails
