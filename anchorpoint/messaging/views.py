import base64
import hashlib
import hmac as _hmac

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt

from core.models import OrganizationSettings
from core.permissions import communications_required

from . import outbound
from people.models import Person

from .forms import EmailBroadcastForm, PhoneBlastForm, SmsBroadcastForm
from .models import Communication, Delivery
from .adapters import CALL_STATUS_WEBHOOK_PATH
from .services import (
    AudioProcessingError,
    get_site_base_url,
    person_pk_from_unsubscribe_token,
    transcode_to_mp3,
)

Channel = Communication.Channel


def _queued_message(comm, noun):
    if comm.scheduled_for:
        return f"{noun} scheduled for {comm.scheduled_for:%b %d, %Y %I:%M %p}."
    return f"{noun} queued. It goes out within a minute."


@communications_required
def communications_home(request):
    broadcasts = Communication.objects.filter(kind=Communication.Kind.BROADCAST).select_related(
        "created_by", "group", "person"
    )
    sms_messages = broadcasts.filter(channel=Channel.SMS)[:5]
    emails = broadcasts.filter(channel=Channel.EMAIL)[:5]
    phone_blasts = broadcasts.filter(channel=Channel.VOICE)[:5]
    context = {
        "sms_messages": sms_messages,
        "emails": emails,
        "email_ready": outbound.channel_ready(Channel.EMAIL),
        "phone_blasts_with_stats": [(b, _blast_stats(b)) for b in phone_blasts],
        "twilio_ready": outbound.channel_ready(Channel.SMS),
    }
    return render(request, "messaging/home.html", context)


@communications_required
def sms_compose(request):
    twilio_ready = outbound.channel_ready(Channel.SMS)
    if request.method == "POST":
        if not twilio_ready:
            messages.error(request, "Configure your Twilio credentials before sending messages.")
            return redirect("organization_settings")
        form = SmsBroadcastForm(request.POST)
        if form.is_valid():
            person, group = form.target()
            try:
                comm = outbound.broadcast(
                    Channel.SMS,
                    created_by=request.user,
                    person=person,
                    group=group,
                    scheduled_for=form.cleaned_data.get("scheduled_for"),
                    body=form.cleaned_data["body"],
                )
            except outbound.BroadcastRejected as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _queued_message(comm, "Message"))
                return redirect("messaging:home")
    else:
        form = SmsBroadcastForm()
    return render(request, "messaging/sms_form.html", {"form": form, "twilio_ready": twilio_ready})


@communications_required
def email_compose(request):
    email_ready = outbound.channel_ready(Channel.EMAIL)
    if request.method == "POST":
        form = EmailBroadcastForm(request.POST)
        if form.is_valid():
            person, group = form.target()
            try:
                comm = outbound.broadcast(
                    Channel.EMAIL,
                    created_by=request.user,
                    person=person,
                    group=group,
                    scheduled_for=form.cleaned_data.get("scheduled_for"),
                    subject=form.cleaned_data["subject"],
                    body=form.cleaned_data["body"],
                )
            except outbound.BroadcastRejected as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _queued_message(comm, "Email"))
                return redirect("messaging:home")
    else:
        form = EmailBroadcastForm()
    return render(request, "messaging/email_form.html", {"form": form, "email_ready": email_ready})


def email_unsubscribe(request, token):
    """Public page from an email's unsubscribe link. GET only asks; the POST turns emails
    off, so mail scanners that prefetch links can't unsubscribe anyone."""
    pk = person_pk_from_unsubscribe_token(token)
    person = Person.objects.filter(pk=pk).first() if pk is not None else None
    if person is None:
        raise Http404("Unknown unsubscribe link")
    done = request.method == "POST"
    if done and person.email_opt_in:
        person.email_opt_in = False
        person.save(update_fields=["email_opt_in"])
    org = OrganizationSettings.load()
    return render(request, "messaging/unsubscribe.html", {"person": person, "done": done, "org": org})


@communications_required
def phone_blast_create(request):
    twilio_ready = outbound.channel_ready(Channel.VOICE)
    if request.method == "POST":
        if not twilio_ready:
            messages.error(request, "Configure your Twilio credentials before sending phone blasts.")
            return redirect("organization_settings")
        form = PhoneBlastForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # Normalise the uploaded/recorded audio to MP3 so Twilio's <Play> can fetch
                # it (browser recordings are WebM/MP4, which Twilio can't play).
                audio = transcode_to_mp3(form.cleaned_data["audio_file"])
            except AudioProcessingError as exc:
                form.add_error("audio_file", str(exc))
            else:
                person, group = form.target()
                try:
                    comm = outbound.broadcast(
                        Channel.VOICE,
                        created_by=request.user,
                        person=person,
                        group=group,
                        scheduled_for=form.cleaned_data.get("scheduled_for"),
                        title=form.cleaned_data["title"],
                        audio_file=audio,
                        notes=form.cleaned_data.get("notes", ""),
                    )
                except outbound.BroadcastRejected as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, _queued_message(comm, "Phone blast"))
                    return redirect("messaging:home")
    else:
        form = PhoneBlastForm()
    return render(
        request, "messaging/phone_blast_form.html", {"form": form, "twilio_ready": twilio_ready}
    )


# ---------------------------------------------------------------------------
# Phone blast detail + HTMX stats partial
# ---------------------------------------------------------------------------

def _get_blast(pk):
    return get_object_or_404(
        Communication.objects.select_related("created_by", "group", "person"),
        pk=pk, channel=Channel.VOICE, kind=Communication.Kind.BROADCAST,
    )


@communications_required
def phone_blast_detail(request, pk):
    """Detail page for a phone blast with call stats and live HTMX polling."""
    blast = _get_blast(pk)
    calls = blast.deliveries.select_related("person").order_by("-completed_at", "address")
    return render(request, "messaging/phone_blast_detail.html", {
        "blast": blast,
        "calls": calls,
        "stats": _blast_stats(blast),
    })


@communications_required
def phone_blast_stats(request, pk):
    """HTMX partial: stats block for a phone blast. Includes polling trigger while sending."""
    blast = _get_blast(pk)
    return render(request, "messaging/phone_blast_stats.html", {
        "blast": blast,
        "stats": _blast_stats(blast),
    })


def _blast_stats(blast):
    """Call outcome counts for a phone blast. Skipped calls (opted out) aren't counted."""
    counts = blast.delivery_counts()
    answered = counts.get(Delivery.Status.ANSWERED, 0)
    no_answer = counts.get(Delivery.Status.NO_ANSWER, 0)
    failed = counts.get(Delivery.Status.FAILED, 0)
    pending = counts.get(Delivery.Status.PENDING, 0) + counts.get(Delivery.Status.SENT, 0)
    total = answered + no_answer + failed + pending
    settled = answered + no_answer + failed
    return {
        "answered": answered,
        "no_answer": no_answer,
        "failed": failed,
        "pending": pending,
        "skipped": counts.get(Delivery.Status.SKIPPED, 0),
        "total": total,
        "settled": settled,
        "percent": round(settled / total * 100) if total else 0,
    }


# ---------------------------------------------------------------------------
# Twilio StatusCallback webhook
# ---------------------------------------------------------------------------

def _validate_twilio_signature(auth_token: str, signature: str, url: str, params: dict) -> bool:
    """Validate Twilio's HMAC-SHA1 request signature."""
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    s = url + sorted_params
    mac = _hmac.new(auth_token.encode("utf-8"), s.encode("utf-8"), hashlib.sha1)
    expected = base64.b64encode(mac.digest()).decode()
    return _hmac.compare_digest(expected, signature)


@csrf_exempt
def phone_call_status_webhook(request):
    """Twilio StatusCallback endpoint, called when a phone-blast call ends."""
    if request.method != "POST":
        return HttpResponse(status=405)

    auth_token = OrganizationSettings.load().twilio_auth_token or ""
    # Fail closed: without a token we can't tell Twilio from a forger.
    if not auth_token:
        return HttpResponseForbidden("Twilio is not configured")
    signature = request.META.get("HTTP_X_TWILIO_SIGNATURE", "")
    # Twilio signs the exact callback URL we registered (public https, from
    # SITE_BASE_URL). Behind Cloudflare Tunnel the request reaches Django on an
    # internal http host, so the rebuilt URL alone never matches.
    candidates = [request.build_absolute_uri()]
    base_url = get_site_base_url()
    if base_url:
        candidates.insert(0, f"{base_url}{CALL_STATUS_WEBHOOK_PATH}")
    params = request.POST.dict()
    if not any(_validate_twilio_signature(auth_token, signature, url, params) for url in candidates):
        return HttpResponseForbidden("Invalid signature")

    call_sid = request.POST.get("CallSid", "")
    delivery = outbound.record_call_status(call_sid, request.POST.get("CallStatus", ""))
    if delivery is None:
        raise Http404(f"No call with CallSid={call_sid!r}")
    return HttpResponse(status=200)
