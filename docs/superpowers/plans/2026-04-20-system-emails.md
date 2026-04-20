# System Emails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automated system emails (welcome, registration confirmation, staff notification, password reset) via Google Workspace SMTP.

**Architecture:** Django's built-in SMTP `EmailBackend` is configured from environment variables. A new `core/email_service.py` module contains all sending functions (mirroring the `messaging/services.py` pattern). Emails are triggered by a `post_save` signal for welcome, direct calls in `events/views.py` for registration emails, and Django's built-in auth flow for password reset.

**Tech Stack:** Django 5.2, `django.core.mail.EmailMultiAlternatives`, `django.template.loader.render_to_string`, Google Workspace SMTP (smtp.gmail.com:587)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `anchorpoint/anchorpoint/settings.py` | Modify | Add EMAIL_* settings from env |
| `.env.production.example` | Modify | Document email env vars |
| `anchorpoint/core/email_service.py` | Create | All email sending functions |
| `anchorpoint/core/models.py` | Modify | Wire welcome email in post_save signal |
| `anchorpoint/core/tests.py` | Modify | Tests for email service + signal |
| `anchorpoint/events/views.py` | Modify | Call email functions after registration |
| `anchorpoint/events/tests.py` | Modify | Tests for registration email triggers |
| `anchorpoint/templates/emails/base.html` | Create | Shared branded email wrapper |
| `anchorpoint/templates/emails/welcome.html` | Create | Welcome email HTML |
| `anchorpoint/templates/emails/welcome.txt` | Create | Welcome email plain text |
| `anchorpoint/templates/emails/registration_confirmation.html` | Create | Confirmation email HTML |
| `anchorpoint/templates/emails/registration_confirmation.txt` | Create | Confirmation email plain text |
| `anchorpoint/templates/emails/staff_new_registration.html` | Create | Staff notification HTML |
| `anchorpoint/templates/emails/staff_new_registration.txt` | Create | Staff notification plain text |
| `anchorpoint/templates/registration/password_reset_email.html` | Create | Override Django's password reset email |
| `anchorpoint/templates/registration/password_reset_subject.txt` | Create | Override Django's password reset subject |

---

## Task 1: Configure SMTP email backend

**Files:**
- Modify: `anchorpoint/anchorpoint/settings.py`
- Modify: `.env.production.example`

- [ ] **Step 1: Add email settings to settings.py**

Open `anchorpoint/anchorpoint/settings.py`. After the `DEFAULT_AUTO_FIELD` line at the bottom, add:

```python
# Email configuration (Google Workspace SMTP)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
```

- [ ] **Step 2: Add email vars to .env.production.example**

Open `.env.production.example`. Add this section after the existing entries:

```env
# Email (Google Workspace SMTP)
# Generate an app password: Google Account > Security > 2-Step Verification > App passwords
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=info@bolivar.church
EMAIL_HOST_PASSWORD=your-google-app-password-here
DEFAULT_FROM_EMAIL=AnchorPoint <info@bolivar.church>
```

- [ ] **Step 3: Commit**

```bash
git add anchorpoint/anchorpoint/settings.py .env.production.example
git commit -m "feat: configure SMTP email backend from environment variables"
```

---

## Task 2: Create the email service module

**Files:**
- Create: `anchorpoint/core/email_service.py`
- Modify: `anchorpoint/core/tests.py`

- [ ] **Step 1: Write failing tests**

Open `anchorpoint/core/tests.py`. Add the following at the bottom of the file (after existing tests):

```python
from django.core import mail
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailServiceTest(TestCase):
    def setUp(self):
        mail.outbox.clear()

    def test_send_welcome_email_sends_to_user(self):
        from core.email_service import send_welcome_email
        user = User.objects.create_user(
            username="emailtest", email="test@example.com", password="pass"
        )
        mail.outbox.clear()  # clear email triggered by user creation signal
        send_welcome_email(user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("test@example.com", mail.outbox[0].to)

    def test_send_welcome_email_does_not_raise_on_failure(self):
        from core.email_service import send_welcome_email
        # User with no email should not raise
        user = User.objects.create_user(
            username="noemail", email="", password="pass"
        )
        mail.outbox.clear()
        send_welcome_email(user)  # must not raise

    def test_send_registration_confirmation_sends_to_registrant(self):
        from core.email_service import send_registration_confirmation
        from events.models import Event, EventRegistration
        event = Event.objects.create(title="Test Event", created_by=None)
        registration = EventRegistration.objects.create(
            event=event,
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
        )
        send_registration_confirmation(registration)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("jane@example.com", mail.outbox[0].to)
        self.assertIn("Test Event", mail.outbox[0].subject)

    def test_send_staff_notification_sends_to_staff(self):
        from core.email_service import send_staff_registration_notification
        from core.models import UserProfile
        from events.models import Event, EventRegistration
        staff_user = User.objects.create_user(
            username="staffuser", email="staff@example.com", password="pass"
        )
        staff_user.profile.role = UserProfile.Role.STAFF
        staff_user.profile.save()
        event = Event.objects.create(title="Test Event", created_by=None)
        registration = EventRegistration.objects.create(
            event=event,
            first_name="John",
            last_name="Smith",
            email="john@example.com",
        )
        mail.outbox.clear()
        send_staff_registration_notification(registration)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("staff@example.com", mail.outbox[0].bcc)

    def test_send_staff_notification_skips_when_no_staff(self):
        from core.email_service import send_staff_registration_notification
        from events.models import Event, EventRegistration
        event = Event.objects.create(title="Test Event", created_by=None)
        registration = EventRegistration.objects.create(
            event=event,
            first_name="John",
            last_name="Smith",
            email="john@example.com",
        )
        mail.outbox.clear()
        send_staff_registration_notification(registration)
        self.assertEqual(len(mail.outbox), 0)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd anchorpoint
python manage.py test core.tests.EmailServiceTest -v 2
```

Expected: `ImportError: cannot import name 'send_welcome_email' from 'core.email_service'` (module doesn't exist yet).

- [ ] **Step 3: Create core/email_service.py**

Create `anchorpoint/core/email_service.py`:

```python
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _send(subject: str, to: list, text_template: str, html_template: str, context: dict, bcc: list = None) -> None:
    """
    Render templates and send an email with HTML and plain-text alternatives.
    Catches all exceptions and logs them — never raises.
    """
    try:
        text_body = render_to_string(text_template, context)
        html_body = render_to_string(html_template, context)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=to,
            bcc=bcc or [],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()
    except Exception:
        logger.exception(
            "Failed to send email '%s' to %s", subject, to
        )


def send_welcome_email(user) -> None:
    """Send a welcome email to a newly created user."""
    if not user.email:
        return
    from core.models import OrganizationSettings
    org = OrganizationSettings.load()
    org_name = org.name or "AnchorPoint"
    _send(
        subject=f"Welcome to {org_name}",
        to=[user.email],
        text_template="emails/welcome.txt",
        html_template="emails/welcome.html",
        context={"user": user, "org": org},
    )


def send_registration_confirmation(registration) -> None:
    """Send a registration confirmation to the registrant."""
    if not registration.email:
        return
    from core.models import OrganizationSettings
    org = OrganizationSettings.load()
    _send(
        subject=f"Registration confirmed: {registration.event.title}",
        to=[registration.email],
        text_template="emails/registration_confirmation.txt",
        html_template="emails/registration_confirmation.html",
        context={"registration": registration, "event": registration.event, "org": org},
    )


def send_staff_registration_notification(registration) -> None:
    """Notify all admin/staff users of a new event registration."""
    from core.models import OrganizationSettings, UserProfile
    staff_emails = list(
        UserProfile.objects.filter(
            role__in=[UserProfile.Role.ADMIN, UserProfile.Role.STAFF]
        )
        .select_related("user")
        .exclude(user__email="")
        .values_list("user__email", flat=True)
    )
    if not staff_emails:
        return
    org = OrganizationSettings.load()
    _send(
        subject=f"New registration: {registration.event.title}",
        to=[settings.DEFAULT_FROM_EMAIL],
        bcc=staff_emails,
        text_template="emails/staff_new_registration.txt",
        html_template="emails/staff_new_registration.html",
        context={"registration": registration, "event": registration.event, "org": org},
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd anchorpoint
python manage.py test core.tests.EmailServiceTest -v 2
```

Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add anchorpoint/core/email_service.py anchorpoint/core/tests.py
git commit -m "feat: add email service module with welcome, confirmation, and staff notification"
```

---

## Task 3: Create email templates

**Files:**
- Create: `anchorpoint/templates/emails/base.html`
- Create: `anchorpoint/templates/emails/welcome.html`
- Create: `anchorpoint/templates/emails/welcome.txt`
- Create: `anchorpoint/templates/emails/registration_confirmation.html`
- Create: `anchorpoint/templates/emails/registration_confirmation.txt`
- Create: `anchorpoint/templates/emails/staff_new_registration.html`
- Create: `anchorpoint/templates/emails/staff_new_registration.txt`
- Create: `anchorpoint/templates/registration/password_reset_email.html`
- Create: `anchorpoint/templates/registration/password_reset_subject.txt`

- [ ] **Step 1: Create base email template**

Create `anchorpoint/templates/emails/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #f4f4f4; font-family: Arial, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f4f4; padding: 20px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 6px; overflow: hidden;">
          <tr>
            <td style="background-color: #1a3a5c; padding: 24px 32px;">
              <p style="margin: 0; color: #ffffff; font-size: 20px; font-weight: bold;">{{ org.name|default:"AnchorPoint" }}</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 32px;">
              {% block content %}{% endblock %}
            </td>
          </tr>
          <tr>
            <td style="background-color: #f9f9f9; padding: 16px 32px; border-top: 1px solid #eeeeee;">
              <p style="margin: 0; color: #999999; font-size: 12px;">{{ org.name|default:"AnchorPoint" }}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
```

- [ ] **Step 2: Create welcome email templates**

Create `anchorpoint/templates/emails/welcome.html`:

```html
{% extends "emails/base.html" %}
{% block content %}
<h2 style="color: #1a3a5c; margin-top: 0;">Welcome, {{ user.first_name|default:user.username }}!</h2>
<p style="color: #444444; line-height: 1.6;">
  Your account has been created for {{ org.name|default:"AnchorPoint" }}.
  You can now log in to access the system.
</p>
<p style="color: #444444; line-height: 1.6;">
  If you have any questions, please reach out to your administrator.
</p>
<p style="color: #444444;">— The {{ org.name|default:"AnchorPoint" }} Team</p>
{% endblock %}
```

Create `anchorpoint/templates/emails/welcome.txt`:

```
Welcome, {{ user.first_name|default:user.username }}!

Your account has been created for {{ org.name|default:"AnchorPoint" }}.
You can now log in to access the system.

If you have any questions, please reach out to your administrator.

— The {{ org.name|default:"AnchorPoint" }} Team
```

- [ ] **Step 3: Create registration confirmation templates**

Create `anchorpoint/templates/emails/registration_confirmation.html`:

```html
{% extends "emails/base.html" %}
{% block content %}
<h2 style="color: #1a3a5c; margin-top: 0;">You're registered!</h2>
<p style="color: #444444; line-height: 1.6;">
  Hi {{ registration.first_name }}, thanks for registering for
  <strong>{{ event.title }}</strong>.
</p>
{% if event.next_occurrence %}
<p style="color: #444444; line-height: 1.6;">
  <strong>Date:</strong> {{ event.next_occurrence.starts_at|date:"F j, Y" }}
  at {{ event.next_occurrence.starts_at|time:"g:i A" }}
</p>
{% endif %}
{% if event.location_name %}
<p style="color: #444444; line-height: 1.6;">
  <strong>Location:</strong> {{ event.location_name }}{% if event.location_city %}, {{ event.location_city }}{% endif %}
</p>
{% endif %}
{% if event.contact_email %}
<p style="color: #444444; line-height: 1.6;">
  Questions? Contact us at
  <a href="mailto:{{ event.contact_email }}" style="color: #1a3a5c;">{{ event.contact_email }}</a>.
</p>
{% endif %}
<p style="color: #444444;">We look forward to seeing you!</p>
<p style="color: #444444;">— {{ org.name|default:"AnchorPoint" }}</p>
{% endblock %}
```

Create `anchorpoint/templates/emails/registration_confirmation.txt`:

```
Hi {{ registration.first_name }},

Thanks for registering for {{ event.title }}!

{% if event.next_occurrence %}Date: {{ event.next_occurrence.starts_at|date:"F j, Y" }} at {{ event.next_occurrence.starts_at|time:"g:i A" }}
{% endif %}{% if event.location_name %}Location: {{ event.location_name }}{% if event.location_city %}, {{ event.location_city }}{% endif %}
{% endif %}
{% if event.contact_email %}Questions? Contact us at {{ event.contact_email }}.{% endif %}

We look forward to seeing you!

— {{ org.name|default:"AnchorPoint" }}
```

- [ ] **Step 4: Create staff notification templates**

Create `anchorpoint/templates/emails/staff_new_registration.html`:

```html
{% extends "emails/base.html" %}
{% block content %}
<h2 style="color: #1a3a5c; margin-top: 0;">New Registration</h2>
<p style="color: #444444; line-height: 1.6;">
  A new registration has been submitted for <strong>{{ event.title }}</strong>.
</p>
<table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
  <tr>
    <td style="padding: 8px 0; color: #666666; width: 140px;">Name</td>
    <td style="padding: 8px 0; color: #222222;">{{ registration.first_name }} {{ registration.last_name }}</td>
  </tr>
  <tr>
    <td style="padding: 8px 0; color: #666666;">Email</td>
    <td style="padding: 8px 0; color: #222222;">{{ registration.email }}</td>
  </tr>
  {% if registration.phone %}
  <tr>
    <td style="padding: 8px 0; color: #666666;">Phone</td>
    <td style="padding: 8px 0; color: #222222;">{{ registration.phone }}</td>
  </tr>
  {% endif %}
  <tr>
    <td style="padding: 8px 0; color: #666666;">Attendees</td>
    <td style="padding: 8px 0; color: #222222;">{{ registration.number_of_attendees }}</td>
  </tr>
  <tr>
    <td style="padding: 8px 0; color: #666666;">Submitted</td>
    <td style="padding: 8px 0; color: #222222;">{{ registration.created_at|date:"F j, Y g:i A" }}</td>
  </tr>
</table>
{% endblock %}
```

Create `anchorpoint/templates/emails/staff_new_registration.txt`:

```
New Registration — {{ event.title }}

Name:      {{ registration.first_name }} {{ registration.last_name }}
Email:     {{ registration.email }}
{% if registration.phone %}Phone:     {{ registration.phone }}
{% endif %}Attendees: {{ registration.number_of_attendees }}
Submitted: {{ registration.created_at|date:"F j, Y g:i A" }}
```

- [ ] **Step 5: Create password reset templates**

Create `anchorpoint/templates/registration/password_reset_subject.txt`:

```
Reset your {{ org.name|default:"AnchorPoint" }} password
```

Create `anchorpoint/templates/registration/password_reset_email.html`:

```
Hi {{ user.first_name|default:user.username }},

We received a request to reset the password for your account.

Click the link below to set a new password. This link expires in 24 hours.

{{ protocol }}://{{ domain }}{% url 'password_reset_confirm' uidb64=uid token=token %}

If you didn't request a password reset, you can ignore this email.
Your password will not change until you click the link above.

— {{ org.name|default:"AnchorPoint" }}
```

**Note:** Django's password reset email template is plain text only (the `.html` extension is misleading — it renders as plain text). Do not add HTML tags.

- [ ] **Step 6: Run full test suite to confirm templates render without errors**

```bash
cd anchorpoint
python manage.py test core.tests.EmailServiceTest -v 2
```

Expected: All 5 tests still pass. If a `TemplateDoesNotExist` error appears, check that template file paths match exactly what's in the service functions.

- [ ] **Step 7: Commit**

```bash
git add anchorpoint/templates/
git commit -m "feat: add email templates for welcome, registration, staff notification, and password reset"
```

---

## Task 4: Wire welcome email to user creation signal

**Files:**
- Modify: `anchorpoint/core/models.py`
- Modify: `anchorpoint/core/tests.py`

- [ ] **Step 1: Write failing test**

Add this test class to `anchorpoint/core/tests.py`:

```python
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class WelcomeEmailSignalTest(TestCase):
    def setUp(self):
        mail.outbox.clear()

    def test_welcome_email_sent_on_user_creation(self):
        User.objects.create_user(
            username="newuser", email="newuser@example.com", password="pass"
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("newuser@example.com", mail.outbox[0].to)

    def test_welcome_email_not_sent_on_user_update(self):
        user = User.objects.create_user(
            username="existing", email="existing@example.com", password="pass"
        )
        mail.outbox.clear()
        user.first_name = "Updated"
        user.save()
        self.assertEqual(len(mail.outbox), 0)
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd anchorpoint
python manage.py test core.tests.WelcomeEmailSignalTest -v 2
```

Expected: `AssertionError: 0 != 1` — no email sent yet.

- [ ] **Step 3: Update the post_save signal in core/models.py**

Open `anchorpoint/core/models.py`. The existing `ensure_user_profile` signal handler is at line 53. Update it to also call `send_welcome_email` on creation:

```python
@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    # Ensure every user has a profile so role checks never fail in templates.
    if created:
        UserProfile.objects.create(user=instance)
        # Send welcome email — import here to avoid circular imports
        from core.email_service import send_welcome_email
        send_welcome_email(instance)
    else:
        UserProfile.objects.get_or_create(user=instance)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd anchorpoint
python manage.py test core.tests.WelcomeEmailSignalTest -v 2
```

Expected: Both tests pass.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd anchorpoint
python manage.py test -v 1
```

Expected: All tests pass. If any test that creates a User fails due to email errors, it means that test's email backend is not set to locmem — investigate the specific test.

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/core/models.py anchorpoint/core/tests.py
git commit -m "feat: send welcome email when a new user account is created"
```

---

## Task 5: Wire registration confirmation and staff notification

**Files:**
- Modify: `anchorpoint/events/views.py`
- Modify: `anchorpoint/events/tests.py`

- [ ] **Step 1: Write failing tests**

Open `anchorpoint/events/tests.py`. Add the following at the bottom:

```python
from django.core import mail
from django.test import TestCase, override_settings, Client
from django.contrib.auth import get_user_model

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationEmailTest(TestCase):
    def setUp(self):
        from events.models import Event
        from django.utils import timezone
        import datetime
        mail.outbox.clear()
        self.client = Client()
        self.event = Event.objects.create(
            title="Summer Camp",
            is_published=True,
            registration_open=True,
        )
        # Add a future occurrence so can_register() passes
        self.event.occurrences.create(
            starts_at=timezone.now() + datetime.timedelta(days=30),
            ends_at=timezone.now() + datetime.timedelta(days=31),
        )

    def _post_registration(self, email="registrant@example.com"):
        return self.client.post(
            f"/register/{self.event.registration_token}/",
            {
                "contact-first_name": "Jane",
                "contact-last_name": "Doe",
                "contact-email": email,
                "attendee-TOTAL_FORMS": "1",
                "attendee-INITIAL_FORMS": "0",
                "attendee-MIN_NUM_FORMS": "0",
                "attendee-MAX_NUM_FORMS": "10",
                "attendee-0-first_name": "Jane",
                "attendee-0-last_name": "Doe",
                "attendee-0-is_minor": "",
            },
        )

    def test_registration_confirmation_sent_to_registrant(self):
        self._post_registration(email="jane@example.com")
        confirmation_emails = [e for e in mail.outbox if "jane@example.com" in e.to]
        self.assertEqual(len(confirmation_emails), 1)
        self.assertIn("Summer Camp", confirmation_emails[0].subject)

    def test_staff_notification_sent_to_staff(self):
        from core.models import UserProfile
        staff = User.objects.create_user(
            username="staff1", email="staff@example.com", password="pass"
        )
        staff.profile.role = UserProfile.Role.STAFF
        staff.profile.save()
        mail.outbox.clear()
        self._post_registration()
        staff_emails = [e for e in mail.outbox if "staff@example.com" in e.bcc]
        self.assertEqual(len(staff_emails), 1)
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
cd anchorpoint
python manage.py test events.tests.RegistrationEmailTest -v 2
```

Expected: Tests fail — no emails sent yet.

- [ ] **Step 3: Update public_event_register in events/views.py**

Open `anchorpoint/events/views.py`. Find the `public_event_register` view. After line `submitted = True` (after `match_registration_attendees(registration)`) add the email calls:

The relevant section currently reads:
```python
            match_registration_attendees(registration)
            submitted = True
            form = None
            attendee_formset = None
```

Update it to:
```python
            match_registration_attendees(registration)
            # Send confirmation to registrant and notify staff
            from core.email_service import (
                send_registration_confirmation,
                send_staff_registration_notification,
            )
            send_registration_confirmation(registration)
            send_staff_registration_notification(registration)
            submitted = True
            form = None
            attendee_formset = None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd anchorpoint
python manage.py test events.tests.RegistrationEmailTest -v 2
```

Expected: Both tests pass.

- [ ] **Step 5: Run full test suite**

```bash
cd anchorpoint
python manage.py test -v 1
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/events/views.py anchorpoint/events/tests.py
git commit -m "feat: send confirmation and staff notification emails on event registration"
```

---

## Task 6: Add email credentials to the droplet and verify end-to-end

This task is manual — no code changes.

- [ ] **Step 1: Generate a Google app password**

On the Google account for `info@bolivar.church`:
1. Go to [myaccount.google.com](https://myaccount.google.com) → Security → 2-Step Verification
2. Scroll to **App passwords** → Create one named `AnchorPoint`
3. Copy the 16-character password (shown only once)

- [ ] **Step 2: Add credentials to .env.production on the droplet**

SSH into the droplet as `deploy` and edit the env file:

```bash
nano /home/deploy/anchorpoint/docker/.env.production
```

Add these lines:
```
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=info@bolivar.church
EMAIL_HOST_PASSWORD=<your-16-char-app-password>
DEFAULT_FROM_EMAIL=AnchorPoint <info@bolivar.church>
```

- [ ] **Step 3: Push and deploy**

On your local machine, push to main:

```bash
git push origin main
```

Then trigger the deploy workflow on GitHub: **Actions → Deploy to Production → Run workflow**.

- [ ] **Step 4: Test password reset end-to-end**

Visit `https://anchorpoint.bolivar.church/accounts/password_reset/`. Enter a real email address for a user in the system. Check that the email arrives with the correct subject and a working reset link.

- [ ] **Step 5: Test welcome email end-to-end**

In the Django admin or staff UI, create a new user with a real email address you can check. Confirm the welcome email arrives.

- [ ] **Step 6: Test registration confirmation end-to-end**

Register for a published event using a real email address. Confirm both the registrant confirmation and the staff notification arrive.
