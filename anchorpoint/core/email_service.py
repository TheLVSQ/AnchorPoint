import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _send(
    subject: str,
    to: list,
    text_template: str,
    html_template: str,
    context: dict,
    bcc: list = None,
) -> None:
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
        logger.exception("Failed to send email '%s' to %s", subject, to)


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
        context={
            "registration": registration,
            "event": registration.event,
            "org": org,
        },
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
        context={
            "registration": registration,
            "event": registration.event,
            "org": org,
        },
    )
