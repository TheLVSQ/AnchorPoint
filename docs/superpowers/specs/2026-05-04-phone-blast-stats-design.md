# Phone Blast Stats & Live Progress — Design Spec

## Overview

Add real-time call outcome stats (answered, no answer, failed) and live progress tracking to the phone blast feature. Uses Twilio's `StatusCallback` to receive call outcomes after each call completes, with HTMX polling for live progress on a new blast detail page.

## Architecture

Three layers:
1. **Twilio StatusCallback** — `initiate_call()` registers a webhook URL so Twilio POSTs back when each call ends
2. **Webhook endpoint** — validates Twilio's HMAC-SHA1 signature, updates `PhoneCall.status`, marks blast complete when all calls settle
3. **Detail page + HTMX polling** — new blast detail view with live-refreshing stats block; home page shows per-blast summary

No model changes needed. `PhoneCall` already has `NO_ANSWER`, `COMPLETED`, `FAILED`, `PENDING` statuses and stores `call_sid`.

## Data Flow

```
deliver_phone_blast() → initiate_call(status_callback_url=...) → Twilio dials
                                                                       ↓
                                                              call ends (any outcome)
                                                                       ↓
                                               POST /communications/phone-blast/webhook/call-status/
                                                                       ↓
                                               validate signature → update PhoneCall.status
                                                                       ↓
                                               if no PENDING remain → PhoneBlast.status = COMPLETED
```

## Status Mapping

Twilio call statuses map to `PhoneCall.Status` as follows:

| Twilio `CallStatus` | `PhoneCall.Status` |
|---------------------|-------------------|
| `completed`         | `COMPLETED`        |
| `no-answer`         | `NO_ANSWER`        |
| `busy`              | `FAILED`           |
| `failed`            | `FAILED`           |
| `canceled`          | `FAILED`           |

## Components

### 1. `services.py` Changes

**`initiate_call()`** gains an optional `status_callback_url` parameter. When provided, three fields are added to the Twilio payload:
- `StatusCallback`: the webhook URL
- `StatusCallbackMethod`: `POST`
- `StatusCallbackEvent`: `completed` (only fire on final state, not intermediate)

**`deliver_phone_blast()`** constructs the callback URL from `base_url`:
```
{base_url}/communications/phone-blast/webhook/call-status/
```
Passes it to each `initiate_call()` invocation.

### 2. Webhook Endpoint

**URL:** `POST /communications/phone-blast/webhook/call-status/`

- Public (no `@login_required`) — Twilio calls this directly
- Validates Twilio's HMAC-SHA1 signature using `OrganizationSettings.twilio_auth_token`
- Signature validation: HMAC-SHA1 of `(full_url + sorted_post_params)` with auth token as key, compared to `X-Twilio-Signature` header using `hmac.compare_digest`
- Returns HTTP 200 (empty) on success; HTTP 403 if signature invalid; HTTP 404 if `CallSid` not found
- If signature validation is skipped when auth token is blank (handles dev/test environments)

**Webhook logic:**
1. Extract `CallSid` and `CallStatus` from POST data
2. Look up `PhoneCall` by `call_sid`
3. Map Twilio status → `PhoneCall.Status` (see table above)
4. Save `PhoneCall.status` and `PhoneCall.completed_at`
5. Check if the blast has any remaining `PENDING` calls
6. If none: set `PhoneBlast.status = COMPLETED` and `PhoneBlast.completed_at = now()`

### 3. Blast Detail Page

**URL:** `GET /communications/phone-blast/<pk>/`  
**Template:** `messaging/phone_blast_detail.html`  
**Permission:** `@communications_required`

Displays:
- Blast header: title, group, sent by, started/completed timestamps, status chip
- Stats block (rendered by the stats partial, included on first load)
- Full call table: person name, phone number, status chip, completed_at time

### 4. Stats Partial

**URL:** `GET /communications/phone-blast/<pk>/stats/`  
**Template:** `messaging/phone_blast_stats.html`  
**Permission:** `@communications_required`

Renders four stat numbers: **Answered · No Answer · Failed · Pending**

HTMX polling behavior:
- When `blast.status == PROCESSING`: the partial includes `hx-trigger="every 5s"` on its root element, causing the browser to keep refreshing
- When `blast.status != PROCESSING` (completed/failed): the partial omits `hx-trigger`, stopping polling automatically

The detail page's stats container:
```html
<div id="blast-stats"
     hx-get="{% url 'messaging:phone_blast_stats' blast.pk %}"
     hx-trigger="load"
     hx-swap="outerHTML">
  {# initial render #}
</div>
```

### 5. Home Page Update

Each blast in the recent list gains a summary line below the title:
- `PROCESSING`: `Sending... (N pending)`
- `COMPLETED`: `12 answered · 3 no answer · 1 failed`
- `FAILED`: `Failed — 0 delivered`
- `SCHEDULED`: `Scheduled for [date]`

Counts come from `blast.calls.values('status').annotate(count=Count('id'))` — one extra query per blast, acceptable for a 5-item list.

## URL Structure

```
/communications/phone-blast/<pk>/           → phone_blast_detail
/communications/phone-blast/<pk>/stats/     → phone_blast_stats (HTMX partial)
/communications/phone-blast/webhook/call-status/  → phone_call_status_webhook
```

## Security

- Webhook validates Twilio HMAC-SHA1 signature on every request
- Uses `hmac.compare_digest` to prevent timing attacks
- Returns 403 (not 400) on invalid signature to avoid leaking info
- No CSRF token required on webhook (exempt via `@csrf_exempt`)
- Webhook only updates `PhoneCall` records — cannot create or delete data

## Files Changed

| File | Change |
|------|--------|
| `messaging/services.py` | Add `status_callback_url` param to `initiate_call()`, pass callback URL in `deliver_phone_blast()` |
| `messaging/views.py` | Add `phone_blast_detail`, `phone_blast_stats`, `phone_call_status_webhook` |
| `messaging/urls.py` | Add 3 new URL patterns |
| `templates/messaging/home.html` | Add per-blast stats summary to the blast list |
| `templates/messaging/phone_blast_detail.html` | New — blast detail page |
| `templates/messaging/phone_blast_stats.html` | New — HTMX stats partial |

No migrations required.

## Testing

- Unit test signature validation function (valid sig, invalid sig, missing sig)
- Unit test status mapping (all 5 Twilio status values)
- Unit test blast completion detection (marks complete when last PENDING call settles)
- Integration test: simulate Twilio POST → verify `PhoneCall.status` updates
- Integration test: all calls settled → verify `PhoneBlast.status = COMPLETED`
