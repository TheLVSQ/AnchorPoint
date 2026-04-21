# Form Help Text Design

**Date:** 2026-04-21
**Status:** Approved

## Overview

Add inline help text to form fields that need explanation — technical fields, non-obvious purposes, or specific formatting requirements. Help text appears as small gray text directly below the input. Fields that are self-explanatory (First Name, Last Name, City, etc.) get no help text.

---

## Approach

Use Django's built-in `help_text` attribute on form fields, set in the Python form class. Templates render it with:

```html
{% if form.fieldname.help_text %}
    <small class="help-text">{{ form.fieldname.help_text }}</small>
{% endif %}
```

This is the single source of truth — one place to read or update a field's hint. The pattern is already in use on `EventForm` (`help_texts` in `Meta`) and `PrinterConfigForm` (`help_texts` in `Meta`), and the `people_form.html` template already has the `{% if field.help_text %}` check for `phone_opt_in`. This work extends that pattern consistently across all forms.

Templates that currently have hardcoded `<p class="help-text">` for specific fields (blackout windows, kiosk PIN in `organization_settings.html`) are updated to use `{{ field.help_text }}` instead.

---

## Fields Getting Help Text

### `core/forms.py` — `OrganizationSettingsForm`

| Field | Help text |
|---|---|
| `twilio_account_sid` | Found on your Twilio Console dashboard. Starts with "AC". |
| `twilio_auth_token` | Your Twilio secret key — keep this private. |
| `twilio_phone_number` | The number messages will be sent from. Use E.164 format: +15551234567. |
| `sms_blackout_start` | Sends will be paused at this time each day (local time). |
| `sms_blackout_end` | Queued sends will resume at this time each day. |
| `kiosk_pin` | Leave blank to disable the PIN requirement. |

### `people/forms.py` — `PersonForm`

| Field | Help text |
|---|---|
| `phone_opt_in` | Allows this person to receive SMS and phone blasts. |
| `security_notes` | Visible to staff during check-in. Use for custody restrictions or pick-up rules. |
| `grade` | Used for automatic room assignment during check-in. |
| `salvation_date` | The date this person made a decision to follow Christ. |
| `baptism_date` | The date this person was baptized. |
| `first_visit_date` | The first date this person attended a service or event. |
| `allergies` | Displayed to staff during check-in for children. |

### `groups/forms.py` — `GroupForm`

| Field | Help text |
|---|---|
| `short_code` | A short identifier used for reporting and quick lookup. |
| `meeting_schedule` | e.g. "Sundays at 9am" — shown on public group listings. |
| `capacity` | Leave blank for unlimited. |

### `messaging/forms.py` — `SmsMessageForm` and `PhoneBlastForm`

| Field | Help text |
|---|---|
| `SmsMessageForm.scheduled_for` | Leave blank to send immediately. Must fall outside your blackout window. |
| `PhoneBlastForm.audio_file` | Upload an MP3 or WAV file. Keep it under 60 seconds for best results. |
| `PhoneBlastForm.scheduled_for` | Leave blank to send immediately. Must fall outside your blackout window. |

### `checkin/forms.py` — `RoomForm` and `CheckInSessionForm`

| Field | Help text |
|---|---|
| `RoomForm.min_age` | Age in years. Used to auto-assign children during check-in. Leave blank if not age-based. |
| `RoomForm.max_age` | Age in years. Leave blank if there is no upper limit. |
| `RoomForm.min_grade` | Leave blank if this room is not grade-based. |
| `RoomForm.max_grade` | Leave blank if there is no upper grade limit. |
| `RoomForm.sort_order` | Lower numbers appear first in the room list. |
| `CheckInSessionForm.rooms` | Select all rooms that should be available during this session. |

### `events/forms.py` — `EventRegistrationAttendeeForm`

| Field | Help text |
|---|---|
| `allergies` | Shared with staff for child safety during the event. |
| `medical_notes` | Any conditions staff should be aware of. |

---

## Template Changes

Each template below needs `{% if field.help_text %}<small class="help-text">{{ field.help_text }}</small>{% endif %}` added after the input for each field listed above.

| Template | Action |
|---|---|
| `templates/core/organization_settings.html` | Replace hardcoded `<p class="help-text">` for blackout/PIN fields; add help rendering for Twilio fields |
| `people/templates/people/people_form.html` | `phone_opt_in` already renders it; add for `security_notes`, `grade`, `salvation_date`, `baptism_date`, `first_visit_date`, `allergies` |
| `groups/templates/groups/group_form.html` | Add for `short_code`, `meeting_schedule`, `capacity` |
| `templates/messaging/sms_form.html` | Add for `scheduled_for` |
| `templates/messaging/phone_blast_form.html` | Add for `audio_file`, `scheduled_for` |
| `checkin/templates/checkin/room_form.html` | Add for `min_age`, `max_age`, `min_grade`, `max_grade`, `sort_order` |
| `checkin/templates/checkin/session_form.html` | Add for `rooms` |
| `events/templates/events/public/event_register.html` | Already loops over fields and renders `field.help_text` — no template change needed, just add `help_text` to the form fields in Python |

---

## CSS

The `.help-text` class is already defined globally in `base.html`. No new CSS needed.

---

## Out of Scope

- Tooltip-on-hover or tooltip-on-focus styles (user selected inline text)
- Help text on public-facing fields that are self-explanatory (name, address, email)
- Help text on check-in kiosk views (those are touch UIs for volunteers, not admin forms)
