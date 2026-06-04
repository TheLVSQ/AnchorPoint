# Phone Blast Stats & Live Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time call outcome stats (answered, no answer, failed) and live progress to phone blasts via Twilio StatusCallback webhooks and HTMX polling.

**Architecture:** `initiate_call()` registers a `StatusCallback` URL with Twilio; a new webhook view receives Twilio's POST after each call ends and updates `PhoneCall.status`; a detail page shows per-blast stats with HTMX polling that auto-stops when the blast completes. No model changes — `PhoneCall` already has `NO_ANSWER`, `COMPLETED`, `FAILED`, and `call_sid`.

**Tech Stack:** Django 5.2, HTMX, Twilio REST API (no SDK — raw urllib like existing code), HMAC-SHA1 signature validation

**Design Spec:** `docs/superpowers/specs/2026-05-04-phone-blast-stats-design.md`

---

## File Structure

### Modified Files
- `anchorpoint/messaging/services.py` — add `status_callback_url` param to `initiate_call()`, pass it through `deliver_phone_blast()`
- `anchorpoint/messaging/views.py` — add `phone_blast_detail`, `phone_blast_stats`, `phone_call_status_webhook`
- `anchorpoint/messaging/urls.py` — add 3 URL patterns
- `anchorpoint/templates/messaging/home.html` — add per-blast stats summary line

### New Files
- `anchorpoint/templates/messaging/phone_blast_detail.html` — blast detail page with HTMX stats container
- `anchorpoint/templates/messaging/phone_blast_stats.html` — HTMX-refreshed stats partial

---

## Task 1: Add StatusCallback to `initiate_call()` and `deliver_phone_blast()`

**Files:**
- Modify: `anchorpoint/messaging/services.py`
- Modify: `anchorpoint/messaging/tests.py`

- [ ] **Step 1: Write the failing test**

Add to `MessagingDeliveryTests` in `anchorpoint/messaging/tests.py`:

```python
def test_deliver_phone_blast_passes_status_callback(self):
    """deliver_phone_blast passes the StatusCallback URL to initiate_call."""
    audio = SimpleUploadedFile("message.mp3", b"audio-bytes")
    blast = PhoneBlast.objects.create(
        created_by=self.user,
        title="Callback Test",
        audio_file=audio,
    )
    PhoneCall.objects.create(
        blast=blast,
        person=self.person,
        phone_number=self.person.phone,
    )
    with patch(
        "messaging.services.TwilioService.initiate_call", return_value="CA999"
    ) as mock_call:
        deliver_phone_blast(
            blast,
            settings_obj=self.settings_obj,
            base_url="https://example.com",
        )
    mock_call.assert_called_once_with(
        self.person.phone,
        "https://example.com/media/message.mp3",
        status_callback_url="https://example.com/communications/phone-blast/webhook/call-status/",
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.MessagingDeliveryTests.test_deliver_phone_blast_passes_status_callback -v2
```
Expected: FAIL — `initiate_call() got an unexpected keyword argument 'status_callback_url'`

- [ ] **Step 3: Update `initiate_call()` in `services.py`**

Replace the existing `initiate_call` method (lines 74–85) with:

```python
def initiate_call(self, to_number: str, audio_url: str, status_callback_url: str = None) -> str:
    twiml = f"<Response><Play>{audio_url}</Play></Response>"
    payload = {
        "To": to_number,
        "From": self.from_number,
        "Twiml": twiml,
    }
    if status_callback_url:
        payload["StatusCallback"] = status_callback_url
        payload["StatusCallbackMethod"] = "POST"
        payload["StatusCallbackEvent"] = "completed"
    response = self._post(
        self.CALLS_ENDPOINT.format(sid=self.account_sid),
        data=payload,
    )
    return response.get("sid", "")
```

- [ ] **Step 4: Update `deliver_phone_blast()` to pass the callback URL**

In `deliver_phone_blast()`, find the line that calls `service.initiate_call(call.phone_number, audio_url)` (around line 218) and replace it:

```python
        callback_url = f"{base_url.rstrip('/')}/communications/phone-blast/webhook/call-status/" if base_url else None
        # ... (keep the existing loop structure, just change the initiate_call call)
```

The full updated `deliver_phone_blast` call loop section (replace from `for call in blast.calls...` to the end of the loop body):

```python
    callback_url = (
        f"{base_url.rstrip('/')}/communications/phone-blast/webhook/call-status/"
        if base_url
        else None
    )
    success_count = 0
    failure_count = 0
    for call in blast.calls.select_related("person"):
        if call.status != PhoneCall.Status.PENDING:
            continue
        try:
            sid = service.initiate_call(call.phone_number, audio_url, status_callback_url=callback_url)
        except (TwilioConfigurationError, TwilioRequestError) as exc:
            call.status = PhoneCall.Status.FAILED
            call.error_message = str(exc)
            call.completed_at = timezone.now()
            call.save(update_fields=["status", "error_message", "completed_at"])
            failure_count += 1
            continue

        call.status = PhoneCall.Status.PENDING  # stays PENDING until webhook fires
        call.call_sid = sid
        call.started_at = timezone.now()
        call.save(update_fields=["status", "call_sid", "started_at"])
        success_count += 1

        if call.person:
            CommunicationLog.objects.create(
                person=call.person,
                communication_type=CommunicationLog.CommunicationType.PHONE,
                summary=f"Phone blast '{blast.title}'",
                detail="Automated call initiated via Twilio.",
                metadata={
                    "phone_number": call.phone_number,
                    "twilio_sid": sid,
                },
                recorded_by=blast.created_by,
                phone_blast=blast,
            )
```

Note: calls now stay `PENDING` after initiation — the webhook will update them when the call actually completes.

Also update the blast completion logic after the loop:

```python
    blast.status = (
        PhoneBlast.Status.PROCESSING if success_count else PhoneBlast.Status.FAILED
    )
    if not success_count:
        blast.completed_at = timezone.now()
    blast.save(update_fields=["status", "completed_at"])
    return success_count, failure_count
```

- [ ] **Step 5: Update the existing `test_deliver_phone_blast_tracks_calls` test**

The existing test asserts `call.status == PhoneCall.Status.COMPLETED` after delivery. Now calls stay `PENDING` after initiation. Update the assertion:

```python
    def test_deliver_phone_blast_tracks_calls(self):
        audio = SimpleUploadedFile("message.mp3", b"audio-bytes")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Weekly Update",
            audio_file=audio,
        )
        PhoneCall.objects.create(
            blast=blast,
            person=self.person,
            phone_number=self.person.phone,
        )
        with patch(
            "messaging.services.TwilioService.initiate_call", return_value="CA123"
        ):
            success, failure = deliver_phone_blast(
                blast, settings_obj=self.settings_obj
            )
        self.assertEqual(success, 1)
        self.assertEqual(failure, 0)
        call = blast.calls.first()
        self.assertEqual(call.status, PhoneCall.Status.PENDING)  # stays PENDING until webhook
        self.assertEqual(call.call_sid, "CA123")
        self.assertEqual(self.person.communication_logs.count(), 1)
        blast.refresh_from_db()
        self.assertEqual(blast.status, PhoneBlast.Status.PROCESSING)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.MessagingDeliveryTests -v2
```
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add anchorpoint/messaging/services.py anchorpoint/messaging/tests.py
git commit -m "feat: pass StatusCallback URL to Twilio when initiating phone blast calls

Calls now stay PENDING after initiation; the webhook will update them
to COMPLETED/NO_ANSWER/FAILED when Twilio reports the outcome."
```

---

## Task 2: Twilio Signature Validation and Webhook View

**Files:**
- Modify: `anchorpoint/messaging/views.py`
- Modify: `anchorpoint/messaging/urls.py`
- Modify: `anchorpoint/messaging/tests.py`

- [ ] **Step 1: Write the failing tests**

Add a new test class to `anchorpoint/messaging/tests.py`. Add these imports at the top of the file if not already present:

```python
import base64
import hashlib
import hmac
import json
from urllib.parse import urlencode
from django.urls import reverse
```

Add the test class:

```python
class PhoneCallWebhookTests(TestCase):
    def setUp(self):
        self.settings_obj = OrganizationSettings.load()
        self.settings_obj.twilio_account_sid = "AC123"
        self.settings_obj.twilio_auth_token = "test_auth_token"
        self.settings_obj.twilio_phone_number = "+15551234567"
        self.settings_obj.save()
        self.user = get_user_model().objects.create_user(
            username="webhookuser", password="pw"
        )
        self.person = Person.objects.create(
            first_name="Jane", last_name="Doe", phone="+15559876543"
        )
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        self.blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Test Blast",
            audio_file=audio,
            status=PhoneBlast.Status.PROCESSING,
        )
        self.call = PhoneCall.objects.create(
            blast=self.blast,
            person=self.person,
            phone_number=self.person.phone,
            call_sid="CA_TEST_001",
            status=PhoneCall.Status.PENDING,
        )
        self.webhook_url = reverse("messaging:phone_call_status_webhook")

    def _make_signature(self, url, params):
        sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
        s = url + sorted_params
        mac = hmac.new(
            self.settings_obj.twilio_auth_token.encode("utf-8"),
            s.encode("utf-8"),
            hashlib.sha1,
        )
        return base64.b64encode(mac.digest()).decode()

    def _post_webhook(self, params, sign=True):
        url = "http://testserver" + self.webhook_url
        sig = self._make_signature(url, params) if sign else "invalidsignature"
        return self.client.post(
            self.webhook_url,
            data=params,
            HTTP_X_TWILIO_SIGNATURE=sig,
        )

    def test_completed_call_marks_completed(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "completed"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.COMPLETED)

    def test_no_answer_marks_no_answer(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "no-answer"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.NO_ANSWER)

    def test_busy_marks_failed(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "busy"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.FAILED)

    def test_failed_marks_failed(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "failed"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 200)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.FAILED)

    def test_blast_marked_complete_when_last_call_settles(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "completed"}
        self._post_webhook(params)
        self.blast.refresh_from_db()
        self.assertEqual(self.blast.status, PhoneBlast.Status.COMPLETED)
        self.assertIsNotNone(self.blast.completed_at)

    def test_blast_stays_processing_while_calls_pending(self):
        # Add a second pending call
        PhoneCall.objects.create(
            blast=self.blast,
            person=self.person,
            phone_number="+15550001111",
            call_sid="CA_TEST_002",
            status=PhoneCall.Status.PENDING,
        )
        params = {"CallSid": "CA_TEST_001", "CallStatus": "completed"}
        self._post_webhook(params)
        self.blast.refresh_from_db()
        self.assertEqual(self.blast.status, PhoneBlast.Status.PROCESSING)

    def test_invalid_signature_returns_403(self):
        params = {"CallSid": "CA_TEST_001", "CallStatus": "completed"}
        response = self._post_webhook(params, sign=False)
        self.assertEqual(response.status_code, 403)
        self.call.refresh_from_db()
        self.assertEqual(self.call.status, PhoneCall.Status.PENDING)

    def test_unknown_call_sid_returns_404(self):
        params = {"CallSid": "CA_UNKNOWN", "CallStatus": "completed"}
        response = self._post_webhook(params)
        self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.PhoneCallWebhookTests -v2
```
Expected: FAIL — `NoReverseMatch: Reverse for 'phone_call_status_webhook' not found`

- [ ] **Step 3: Add the webhook view to `views.py`**

Add these imports to the top of `anchorpoint/messaging/views.py` (after existing imports):

```python
import base64
import hashlib
import hmac as _hmac

from django.http import HttpResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
```

Add this view at the end of `views.py`:

```python
TWILIO_STATUS_MAP = {
    "completed": PhoneCall.Status.COMPLETED,
    "no-answer": PhoneCall.Status.NO_ANSWER,
    "busy": PhoneCall.Status.FAILED,
    "failed": PhoneCall.Status.FAILED,
    "canceled": PhoneCall.Status.FAILED,
}


def _validate_twilio_signature(auth_token: str, signature: str, url: str, params: dict) -> bool:
    """Validate Twilio's HMAC-SHA1 request signature."""
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    s = url + sorted_params
    mac = _hmac.new(auth_token.encode("utf-8"), s.encode("utf-8"), hashlib.sha1)
    expected = base64.b64encode(mac.digest()).decode()
    return _hmac.compare_digest(expected, signature)


@csrf_exempt
def phone_call_status_webhook(request):
    """
    Twilio StatusCallback endpoint. Called by Twilio when a phone call ends.
    Updates PhoneCall.status and marks the blast complete when all calls settle.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    settings_obj = OrganizationSettings.load()
    auth_token = settings_obj.twilio_auth_token or ""

    if auth_token:
        signature = request.META.get("HTTP_X_TWILIO_SIGNATURE", "")
        full_url = request.build_absolute_uri()
        if not _validate_twilio_signature(auth_token, signature, full_url, request.POST.dict()):
            return HttpResponseForbidden("Invalid signature")

    call_sid = request.POST.get("CallSid", "")
    twilio_status = request.POST.get("CallStatus", "")

    try:
        call = PhoneCall.objects.select_related("blast").get(call_sid=call_sid)
    except PhoneCall.DoesNotExist:
        from django.http import Http404
        raise Http404(f"No PhoneCall with call_sid={call_sid!r}")

    new_status = TWILIO_STATUS_MAP.get(twilio_status)
    if new_status:
        call.status = new_status
        call.completed_at = timezone.now()
        call.save(update_fields=["status", "completed_at"])

        # Mark blast complete if no more pending calls
        blast = call.blast
        if not blast.calls.filter(status=PhoneCall.Status.PENDING).exists():
            blast.status = PhoneBlast.Status.COMPLETED
            blast.completed_at = timezone.now()
            blast.save(update_fields=["status", "completed_at"])

    return HttpResponse(status=200)
```

- [ ] **Step 4: Add the webhook URL to `urls.py`**

Replace the contents of `anchorpoint/messaging/urls.py` with:

```python
from django.urls import path

from . import views


app_name = "messaging"

urlpatterns = [
    path("", views.communications_home, name="home"),
    path("sms/new/", views.sms_compose, name="sms_compose"),
    path("phone-blasts/new/", views.phone_blast_create, name="phone_blast_create"),
    path("phone-blast/<int:pk>/", views.phone_blast_detail, name="phone_blast_detail"),
    path("phone-blast/<int:pk>/stats/", views.phone_blast_stats, name="phone_blast_stats"),
    path("phone-blast/webhook/call-status/", views.phone_call_status_webhook, name="phone_call_status_webhook"),
]
```

Note: the webhook URL is defined before `<int:pk>/` patterns to avoid any ambiguity.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.PhoneCallWebhookTests -v2
```
Expected: FAIL — `AttributeError: module 'messaging.views' has no attribute 'phone_blast_detail'`

(The webhook tests should now pass, but the URL file references views not yet defined. Add stub views to unblock.)

Add stubs at the end of `views.py` temporarily:

```python
@communications_required
def phone_blast_detail(request, pk):
    blast = get_object_or_404(PhoneBlast, pk=pk)
    return render(request, "messaging/phone_blast_detail.html", {"blast": blast})


@communications_required
def phone_blast_stats(request, pk):
    blast = get_object_or_404(PhoneBlast, pk=pk)
    return render(request, "messaging/phone_blast_stats.html", {"blast": blast})
```

- [ ] **Step 6: Run webhook tests again**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.PhoneCallWebhookTests -v2
```
Expected: All 8 tests PASS

- [ ] **Step 7: Commit**

```bash
git add anchorpoint/messaging/views.py anchorpoint/messaging/urls.py anchorpoint/messaging/tests.py
git commit -m "feat: add Twilio StatusCallback webhook to update phone call outcomes

Validates HMAC-SHA1 signature, maps Twilio status to PhoneCall.Status,
and marks blast COMPLETED when all calls settle."
```

---

## Task 3: Blast Detail View, Stats View, and Templates

**Files:**
- Modify: `anchorpoint/messaging/views.py` (replace stubs with real implementations)
- Create: `anchorpoint/templates/messaging/phone_blast_detail.html`
- Create: `anchorpoint/templates/messaging/phone_blast_stats.html`
- Modify: `anchorpoint/messaging/tests.py`

- [ ] **Step 1: Write the failing tests**

Add a new test class to `anchorpoint/messaging/tests.py`:

```python
class PhoneBlastDetailViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="staffuser", password="pw"
        )
        from core.models import UserProfile
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

        self.person = Person.objects.create(
            first_name="Test", last_name="Person", phone="+15551112222"
        )
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        self.blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Sunday Announcement",
            audio_file=audio,
            status=PhoneBlast.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=self.blast, person=self.person,
            phone_number=self.person.phone,
            call_sid="CA001", status=PhoneCall.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=self.blast, person=self.person,
            phone_number="+15550000001",
            call_sid="CA002", status=PhoneCall.Status.NO_ANSWER,
        )

    def test_detail_page_returns_200(self):
        response = self.client.get(
            reverse("messaging:phone_blast_detail", args=[self.blast.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sunday Announcement")

    def test_stats_partial_returns_counts(self):
        response = self.client.get(
            reverse("messaging:phone_blast_stats", args=[self.blast.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1")  # 1 answered
        self.assertContains(response, "1")  # 1 no answer

    def test_stats_partial_includes_polling_when_processing(self):
        self.blast.status = PhoneBlast.Status.PROCESSING
        self.blast.save()
        response = self.client.get(
            reverse("messaging:phone_blast_stats", args=[self.blast.pk])
        )
        self.assertContains(response, "every 5s")

    def test_stats_partial_omits_polling_when_complete(self):
        response = self.client.get(
            reverse("messaging:phone_blast_stats", args=[self.blast.pk])
        )
        self.assertNotContains(response, "every 5s")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.PhoneBlastDetailViewTests -v2
```
Expected: FAIL — `TemplateDoesNotExist: messaging/phone_blast_detail.html`

- [ ] **Step 3: Implement the real views (replace stubs)**

Replace the two stub views at the end of `views.py` with:

```python
@communications_required
def phone_blast_detail(request, pk):
    """Detail page for a phone blast with call stats and live HTMX polling."""
    blast = get_object_or_404(PhoneBlast, pk=pk)
    calls = blast.calls.select_related("person").order_by("-completed_at", "phone_number")
    stats = _blast_stats(blast)
    return render(request, "messaging/phone_blast_detail.html", {
        "blast": blast,
        "calls": calls,
        "stats": stats,
    })


@communications_required
def phone_blast_stats(request, pk):
    """HTMX partial: stats block for a phone blast. Includes polling trigger while PROCESSING."""
    blast = get_object_or_404(PhoneBlast, pk=pk)
    stats = _blast_stats(blast)
    return render(request, "messaging/phone_blast_stats.html", {
        "blast": blast,
        "stats": stats,
    })


def _blast_stats(blast):
    """Return a dict of call outcome counts for a blast."""
    from django.db.models import Count
    counts = {
        row["status"]: row["count"]
        for row in blast.calls.values("status").annotate(count=Count("id"))
    }
    return {
        "answered": counts.get(PhoneCall.Status.COMPLETED, 0),
        "no_answer": counts.get(PhoneCall.Status.NO_ANSWER, 0),
        "failed": counts.get(PhoneCall.Status.FAILED, 0),
        "pending": counts.get(PhoneCall.Status.PENDING, 0),
        "total": blast.calls.count(),
    }
```

- [ ] **Step 4: Create `phone_blast_detail.html`**

Create `anchorpoint/templates/messaging/phone_blast_detail.html`:

```html
{% extends "base.html" %}
{% block content %}

<a class="ghost-link" href="{% url 'messaging:home' %}">&larr; Back to Communications</a>

<div class="page-header">
    <h1>{{ blast.title }}</h1>
    <p class="page-subtitle">
        {% if blast.group %}{{ blast.group.name }} &middot; {% endif %}
        Sent by {{ blast.created_by.get_full_name|default:blast.created_by.username }}
        {% if blast.started_at %}&middot; {{ blast.started_at|date:"M j, Y g:i a" }}{% endif %}
        &middot;
        {% if blast.status == "processing" %}
            <span class="chip" style="background:#fef9c3;color:#854d0e;">Sending...</span>
        {% elif blast.status == "completed" %}
            <span class="chip" style="background:#dcfce7;color:#166534;">Completed</span>
        {% else %}
            <span class="chip">{{ blast.get_status_display }}</span>
        {% endif %}
    </p>
</div>

<div id="blast-stats"
     hx-get="{% url 'messaging:phone_blast_stats' blast.pk %}"
     hx-trigger="load"
     hx-swap="outerHTML">
    {% include "messaging/phone_blast_stats.html" %}
</div>

<section class="detail-card" style="margin-top: 2rem;">
    <h2>Calls</h2>
    <div class="list-card__body">
        {% for call in calls %}
            <div class="list-item">
                <div>
                    <strong>{{ call.person.get_full_name|default:call.phone_number }}</strong>
                    <span class="muted-text">{{ call.phone_number }}</span>
                </div>
                <div style="display:flex;align-items:center;gap:0.75rem;">
                    {% if call.completed_at %}
                        <span class="muted-text">{{ call.completed_at|time:"g:i a" }}</span>
                    {% endif %}
                    {% if call.status == "completed" %}
                        <span class="chip" style="background:#dcfce7;color:#166534;">Answered</span>
                    {% elif call.status == "no_answer" %}
                        <span class="chip">No Answer</span>
                    {% elif call.status == "failed" %}
                        <span class="chip" style="background:#fee2e2;color:#991b1b;">Failed</span>
                    {% else %}
                        <span class="chip" style="background:#fef9c3;color:#854d0e;">Pending</span>
                    {% endif %}
                </div>
            </div>
        {% empty %}
            <p class="empty-state">No calls recorded yet.</p>
        {% endfor %}
    </div>
</section>

{% endblock %}
```

- [ ] **Step 5: Create `phone_blast_stats.html`**

Create `anchorpoint/templates/messaging/phone_blast_stats.html`:

```html
<div id="blast-stats"
     {% if blast.status == "processing" %}
     hx-get="{% url 'messaging:phone_blast_stats' blast.pk %}"
     hx-trigger="every 5s"
     hx-swap="outerHTML"
     {% endif %}>

    <div class="detail-grid" style="margin-top:1rem;">
        <section class="detail-card" style="text-align:center;">
            <div style="font-size:2.5rem;font-weight:700;color:#16a34a;">{{ stats.answered }}</div>
            <div class="stat-hint">Answered</div>
        </section>
        <section class="detail-card" style="text-align:center;">
            <div style="font-size:2.5rem;font-weight:700;">{{ stats.no_answer }}</div>
            <div class="stat-hint">No Answer</div>
        </section>
        <section class="detail-card" style="text-align:center;">
            <div style="font-size:2.5rem;font-weight:700;color:#dc2626;">{{ stats.failed }}</div>
            <div class="stat-hint">Failed</div>
        </section>
        <section class="detail-card" style="text-align:center;">
            <div style="font-size:2.5rem;font-weight:700;color:#ca8a04;">{{ stats.pending }}</div>
            <div class="stat-hint">Pending</div>
        </section>
    </div>

</div>
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.PhoneBlastDetailViewTests -v2
```
Expected: All 4 tests PASS

- [ ] **Step 7: Commit**

```bash
git add anchorpoint/messaging/views.py anchorpoint/templates/messaging/
git commit -m "feat: add phone blast detail page with HTMX live stats

Detail page shows per-call outcomes and a stats block that polls
every 5s while the blast is PROCESSING and stops when complete."
```

---

## Task 4: Update Home Page with Per-Blast Stats Summary

**Files:**
- Modify: `anchorpoint/templates/messaging/home.html`
- Modify: `anchorpoint/messaging/views.py` (add stats to context)
- Modify: `anchorpoint/messaging/tests.py`

- [ ] **Step 1: Write the failing test**

Add to `anchorpoint/messaging/tests.py`:

```python
class MessagingHomeViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="staffuser2", password="pw"
        )
        from core.models import UserProfile
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

    def test_home_shows_blast_stats_summary(self):
        person = Person.objects.create(
            first_name="A", last_name="B", phone="+15550001111"
        )
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="Test Blast",
            audio_file=audio,
            status=PhoneBlast.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=blast, person=person,
            phone_number=person.phone,
            call_sid="CA01", status=PhoneCall.Status.COMPLETED,
        )
        PhoneCall.objects.create(
            blast=blast, person=person,
            phone_number="+15550002222",
            call_sid="CA02", status=PhoneCall.Status.NO_ANSWER,
        )
        response = self.client.get(reverse("messaging:home"))
        self.assertContains(response, "1 answered")
        self.assertContains(response, "1 no answer")

    def test_home_shows_sending_label_when_processing(self):
        audio = SimpleUploadedFile("blast.mp3", b"audio")
        blast = PhoneBlast.objects.create(
            created_by=self.user,
            title="In Progress",
            audio_file=audio,
            status=PhoneBlast.Status.PROCESSING,
        )
        PhoneCall.objects.create(
            blast=blast, person=Person.objects.create(
                first_name="X", last_name="Y", phone="+15550003333"
            ),
            phone_number="+15550003333",
            status=PhoneCall.Status.PENDING,
        )
        response = self.client.get(reverse("messaging:home"))
        self.assertContains(response, "Sending")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.MessagingHomeViewTests -v2
```
Expected: FAIL — home page doesn't show "1 answered" yet

- [ ] **Step 3: Update `communications_home` view to include stats**

In `anchorpoint/messaging/views.py`, update `communications_home`:

```python
@communications_required
def communications_home(request):
    from django.db.models import Count
    sms_messages = SmsMessage.objects.select_related("created_by").order_by("-created_at")[:5]
    phone_blasts = PhoneBlast.objects.select_related("created_by").order_by("-created_at")[:5]
    settings_obj = OrganizationSettings.load()

    # Annotate blasts with call outcome counts for the summary line
    blast_stats = {}
    for blast in phone_blasts:
        counts = {
            row["status"]: row["count"]
            for row in blast.calls.values("status").annotate(count=Count("id"))
        }
        blast_stats[blast.pk] = {
            "answered": counts.get(PhoneCall.Status.COMPLETED, 0),
            "no_answer": counts.get(PhoneCall.Status.NO_ANSWER, 0),
            "failed": counts.get(PhoneCall.Status.FAILED, 0),
            "pending": counts.get(PhoneCall.Status.PENDING, 0),
        }

    context = {
        "sms_messages": sms_messages,
        "phone_blasts": phone_blasts,
        "blast_stats": blast_stats,
        "twilio_ready": _twilio_ready(settings_obj),
    }
    return render(request, "messaging/home.html", context)
```

- [ ] **Step 4: Update `home.html` phone blast list**

In `anchorpoint/templates/messaging/home.html`, replace the phone blasts `{% for blast in phone_blasts %}` block:

```html
    {% if phone_blasts %}
        <div class="list-card__body">
            {% for blast in phone_blasts %}
                {% with stats=blast_stats|get_item:blast.pk %}
                <div class="list-item">
                    <div>
                        <strong>
                            <a href="{% url 'messaging:phone_blast_detail' blast.pk %}" class="ghost-link">
                                {{ blast.title }}
                            </a>
                        </strong>
                        <span>
                            {% if blast.status == "processing" %}
                                Sending&hellip;
                                {% if stats.pending %}({{ stats.pending }} pending){% endif %}
                            {% elif blast.status == "completed" %}
                                {% if stats.answered %}{{ stats.answered }} answered{% endif %}
                                {% if stats.no_answer %} &middot; {{ stats.no_answer }} no answer{% endif %}
                                {% if stats.failed %} &middot; {{ stats.failed }} failed{% endif %}
                            {% elif blast.status == "scheduled" %}
                                Scheduled {{ blast.scheduled_for|date:"M j, g:ia" }}
                            {% else %}
                                {{ blast.get_status_display }}
                            {% endif %}
                        </span>
                    </div>
                    <div class="muted-text">
                        {{ blast.created_by.get_full_name|default:blast.created_by.username }}
                    </div>
                </div>
                {% endwith %}
            {% endfor %}
        </div>
    {% else %}
        <p class="empty-state">No phone blasts yet. Upload your first recording above.</p>
    {% endif %}
```

The `|get_item` filter doesn't exist by default. Instead use a simpler approach — pass `blast_stats` as a dict and access it with `blast_stats[blast.pk]`. Django templates can't do dict lookups with variable keys directly, so restructure the context to use a list of `(blast, stats)` tuples instead:

Update `communications_home` in `views.py` to zip blasts with their stats:

```python
    blast_stats = {}
    for blast in phone_blasts:
        counts = {
            row["status"]: row["count"]
            for row in blast.calls.values("status").annotate(count=Count("id"))
        }
        blast_stats[blast.pk] = {
            "answered": counts.get(PhoneCall.Status.COMPLETED, 0),
            "no_answer": counts.get(PhoneCall.Status.NO_ANSWER, 0),
            "failed": counts.get(PhoneCall.Status.FAILED, 0),
            "pending": counts.get(PhoneCall.Status.PENDING, 0),
        }

    phone_blasts_with_stats = [(b, blast_stats[b.pk]) for b in phone_blasts]

    context = {
        "sms_messages": sms_messages,
        "phone_blasts_with_stats": phone_blasts_with_stats,
        "twilio_ready": _twilio_ready(settings_obj),
    }
```

Then update `home.html` to use `phone_blasts_with_stats`:

```html
    {% if phone_blasts_with_stats %}
        <div class="list-card__body">
            {% for blast, stats in phone_blasts_with_stats %}
                <div class="list-item">
                    <div>
                        <strong>
                            <a href="{% url 'messaging:phone_blast_detail' blast.pk %}" class="ghost-link">
                                {{ blast.title }}
                            </a>
                        </strong>
                        <span>
                            {% if blast.status == "processing" %}
                                Sending&hellip;{% if stats.pending %} ({{ stats.pending }} pending){% endif %}
                            {% elif blast.status == "completed" %}
                                {{ stats.answered }} answered{% if stats.no_answer %} &middot; {{ stats.no_answer }} no answer{% endif %}{% if stats.failed %} &middot; {{ stats.failed }} failed{% endif %}
                            {% elif blast.status == "scheduled" %}
                                Scheduled {{ blast.scheduled_for|date:"M j, g:ia" }}
                            {% else %}
                                {{ blast.get_status_display }}
                            {% endif %}
                        </span>
                    </div>
                    <div class="muted-text">
                        {{ blast.created_by.get_full_name|default:blast.created_by.username }}
                    </div>
                </div>
            {% endfor %}
        </div>
    {% else %}
        <p class="empty-state">No phone blasts yet. Upload your first recording above.</p>
    {% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging.tests.MessagingHomeViewTests -v2
```
Expected: All 2 tests PASS

- [ ] **Step 6: Run full messaging test suite**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging -v2
```
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add anchorpoint/messaging/views.py anchorpoint/templates/messaging/home.html anchorpoint/messaging/tests.py
git commit -m "feat: add per-blast stats summary to messaging home page

Each blast in the recent list shows answered/no-answer/failed counts
for completed blasts, or a pending count while sending. Blast title
links to the detail page."
```

---

## Task 5: Final Verification

- [ ] **Step 1: Run full messaging test suite**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test messaging -v2
```
Expected: All tests PASS

- [ ] **Step 2: Run system check**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Manual verification checklist**

Start the dev server and verify:

1. **Home page** — go to `/communications/` and confirm existing blast rows show status info (no crashes)
2. **Create a test blast** — create a blast to a group; after sending confirm calls stay `PENDING` (not immediately `COMPLETED`)
3. **Simulate a webhook** — use curl to simulate Twilio posting back:
   ```bash
   curl -X POST http://localhost:8000/communications/phone-blast/webhook/call-status/ \
     -d "CallSid=CA_TEST&CallStatus=completed"
   ```
   (With no auth token configured, signature validation is skipped — good for local dev)
4. **Detail page** — go to `/communications/phone-blast/<pk>/` and confirm stats render
5. **HTMX polling** — while a blast is PROCESSING, the stats block should auto-refresh every 5s (inspect network tab); once COMPLETED the polling stops
6. **Webhook security** — confirm a request with wrong `X-Twilio-Signature` returns 403

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found during manual verification"
```
