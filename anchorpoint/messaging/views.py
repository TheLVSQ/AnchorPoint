import base64
import hashlib
import hmac as _hmac

from django.contrib import messages
from django.db.models import Count
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from core.models import OrganizationSettings
from core.permissions import communications_required

from .forms import PhoneBlastForm, SmsMessageForm
from .models import PhoneBlast, PhoneCall, SmsMessage, SmsRecipient
from .services import (
    TwilioConfigurationError,
    TwilioRequestError,
    deliver_phone_blast,
    deliver_sms_message,
)


def _twilio_ready(settings_obj: OrganizationSettings) -> bool:
    return all(
        [
            settings_obj.twilio_account_sid,
            settings_obj.twilio_auth_token,
            settings_obj.twilio_phone_number,
        ]
    )


@communications_required
def communications_home(request):

    sms_messages = SmsMessage.objects.select_related("created_by").order_by("-created_at")[
        :5
    ]
    phone_blasts = PhoneBlast.objects.select_related("created_by").order_by("-created_at")[
        :5
    ]
    settings_obj = OrganizationSettings.load()
    context = {
        "sms_messages": sms_messages,
        "phone_blasts": phone_blasts,
        "twilio_ready": _twilio_ready(settings_obj),
    }
    return render(request, "messaging/home.html", context)


@communications_required
def sms_compose(request):

    settings_obj = OrganizationSettings.load()
    twilio_ready = _twilio_ready(settings_obj)

    if request.method == "POST":
        if not twilio_ready:
            messages.error(
                request, "Configure your Twilio credentials before sending messages."
            )
            return redirect("organization_settings")
        form = SmsMessageForm(
            request.POST,
            organization_settings=settings_obj,
        )
        if form.is_valid():
            sms_message = form.save(commit=False)
            sms_message.created_by = request.user
            sms_message.status = (
                SmsMessage.Status.SCHEDULED
                if sms_message.scheduled_for
                else SmsMessage.Status.PROCESSING
            )
            sms_message.save()
            recipients = [
                SmsRecipient(
                    message=sms_message,
                    person=person,
                    phone_number=person.phone or "",
                )
                for person in form.get_recipients()
            ]
            SmsRecipient.objects.bulk_create(recipients)

            if sms_message.scheduled_for:
                messages.success(
                    request,
                    f"Message scheduled for {sms_message.scheduled_for:%b %d, %Y %I:%M %p}.",
                )
            else:
                try:
                    deliver_sms_message(sms_message, settings_obj=settings_obj)
                except (TwilioConfigurationError, TwilioRequestError) as exc:
                    messages.error(request, f"Unable to send via Twilio: {exc}")
                else:
                    messages.success(request, "SMS sent successfully.")
            return redirect("messaging:home")
    else:
        form = SmsMessageForm(organization_settings=settings_obj)

    return render(
        request,
        "messaging/sms_form.html",
        {
            "form": form,
            "twilio_ready": twilio_ready,
        },
    )


@communications_required
def phone_blast_create(request):

    settings_obj = OrganizationSettings.load()
    twilio_ready = _twilio_ready(settings_obj)

    if request.method == "POST":
        if not twilio_ready:
            messages.error(
                request, "Configure your Twilio credentials before sending phone blasts."
            )
            return redirect("organization_settings")
        form = PhoneBlastForm(
            request.POST,
            request.FILES,
            organization_settings=settings_obj,
        )
        if form.is_valid():
            blast = form.save(commit=False)
            blast.created_by = request.user
            blast.status = (
                PhoneBlast.Status.SCHEDULED
                if blast.scheduled_for
                else PhoneBlast.Status.PROCESSING
            )
            blast.save()
            calls = [
                PhoneCall(
                    blast=blast,
                    person=person,
                    phone_number=person.phone or "",
                )
                for person in form.get_recipients()
            ]
            PhoneCall.objects.bulk_create(calls)

            if blast.scheduled_for:
                messages.success(
                    request,
                    f"Phone blast scheduled for {blast.scheduled_for:%b %d, %Y %I:%M %p}.",
                )
            else:
                try:
                    # Build base URL for audio file access
                    base_url = request.build_absolute_uri("/").rstrip("/")
                    deliver_phone_blast(
                        blast,
                        settings_obj=settings_obj,
                        base_url=base_url,
                    )
                except (TwilioConfigurationError, TwilioRequestError) as exc:
                    messages.error(request, f"Unable to start calls: {exc}")
                else:
                    messages.success(request, "Phone blast started.")
            return redirect("messaging:home")
    else:
        form = PhoneBlastForm(organization_settings=settings_obj)

    return render(
        request,
        "messaging/phone_blast_form.html",
        {
            "form": form,
            "twilio_ready": twilio_ready,
        },
    )


# ---------------------------------------------------------------------------
# Phone blast detail + HTMX stats partial
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Twilio StatusCallback webhook
# ---------------------------------------------------------------------------

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
