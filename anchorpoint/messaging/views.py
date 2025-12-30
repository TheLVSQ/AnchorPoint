from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from core.models import OrganizationSettings

from .forms import PhoneBlastForm, SmsMessageForm
from .models import PhoneBlast, PhoneCall, SmsMessage, SmsRecipient
from .services import (
    TwilioConfigurationError,
    TwilioRequestError,
    deliver_phone_blast,
    deliver_sms_message,
)


def _has_access(user):
    if not user.is_authenticated:
        return False
    profile = getattr(user, "profile", None)
    return bool(profile and profile.has_communications_access)


def _twilio_ready(settings_obj: OrganizationSettings) -> bool:
    return all(
        [
            settings_obj.twilio_account_sid,
            settings_obj.twilio_auth_token,
            settings_obj.twilio_phone_number,
        ]
    )


@login_required
def communications_home(request):
    if not _has_access(request.user):
        return HttpResponseForbidden("You do not have permission to use communications.")

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


@login_required
def sms_compose(request):
    if not _has_access(request.user):
        return HttpResponseForbidden("You do not have permission to send SMS messages.")

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


@login_required
def phone_blast_create(request):
    if not _has_access(request.user):
        return HttpResponseForbidden("You do not have permission to send phone blasts.")

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
                    deliver_phone_blast(blast, settings_obj=settings_obj)
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
