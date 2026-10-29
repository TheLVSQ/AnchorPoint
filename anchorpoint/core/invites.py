"""Inviting a person to log in, and the set-your-password links behind it.

``invite(person, base_url=...)`` gives the person a login (email = login, one login per
address), linked to their Person, as a **Team Member** unless they already have a login,
and emails a set-your-password link. The link is Django's password-reset token, so it works
once: setting a password or signing in ends it, and it expires after
``PASSWORD_RESET_TIMEOUT``. "Forgot password?" uses the same links.
"""
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .email_service import send_invite_email
from .models import UserProfile

User = get_user_model()


class InviteError(Exception):
    """Why this person can't be invited. The message is shown to staff."""


@dataclass
class InviteResult:
    user: object
    created: bool  # a new login was made (False: an existing one was reused)
    sent: bool  # the invite email was accepted by the mail server


def link_expiry_days():
    return max(1, settings.PASSWORD_RESET_TIMEOUT // 86400)


def login_for(person):
    """The User linked to this person, or None."""
    profile = UserProfile.objects.filter(person=person).select_related("user").first()
    return profile.user if profile else None


def set_password_url(user, base_url):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{base_url}{reverse('password_reset_confirm', args=[uid, token])}"


def invite(person, *, invited_by, base_url):
    """Create or reuse ``person``'s login and email them a set-your-password link.
    Raises InviteError when they have no email, already signed in, or their email is
    another person's login."""
    name = person.first_name or "This person"
    email = (person.email or "").strip()
    if not email:
        raise InviteError(f"Add an email address to {name}'s profile first.")

    user, created = login_for(person), False
    if user is None:
        user = User.objects.filter(email__iexact=email).select_related("profile").first()
        if user is not None:
            other = user.profile.person
            if other is not None and other.pk != person.pk:
                raise InviteError(
                    f"{email} is already the login for {other.first_name} {other.last_name}. "
                    "Each login needs its own email address."
                )
            user.profile.person = person
            user.profile.save(update_fields=["person"])
        else:
            user = _create_login(person, email)
            created = True

    if user.last_login is not None:
        raise InviteError(
            f"{name} already has a login and has signed in. "
            "They can use \"Forgot password?\" on the sign-in page."
        )
    if not user.is_active:
        raise InviteError(f"{name}'s login is turned off. An admin can turn it on under Users.")

    sent = send_invite_email(
        user, set_password_url(user, base_url), invited_by=invited_by,
        expires_days=link_expiry_days(),
    )
    return InviteResult(user=user, created=created, sent=sent)


def _create_login(person, email):
    user = User(username=email, email=email, first_name=person.first_name,
                last_name=person.last_name)
    user._skip_welcome_email = True  # they get the invite email instead
    user.set_unusable_password()
    user.save()
    profile = user.profile
    profile.role = UserProfile.Role.TEAM_MEMBER
    profile.person = person
    profile.save(update_fields=["role", "person"])
    return user
