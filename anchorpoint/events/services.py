import re
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person

from .models import EventRegistration, EventRegistrationAttendee


def _split_name(full_name: str) -> Tuple[str, str]:
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def _match_person(email="", first_name="", last_name="", birthdate=None, phone=""):
    email = (email or "").strip()
    if email:
        person = Person.objects.filter(email__iexact=email).first()
        if person:
            return person
    if birthdate:
        qs = Person.objects.filter(
            first_name__iexact=first_name.strip(),
            last_name__iexact=last_name.strip(),
            birthdate=birthdate,
        )
        person = qs.first()
        if person:
            return person
    phone_normalized = _normalize_phone(phone)
    if phone_normalized:
        for candidate in Person.objects.exclude(phone="").iterator():
            if _normalize_phone(candidate.phone) == phone_normalized:
                return candidate
    return None


def _apply_contact_data(person: Person, data: dict) -> Person:
    changed = False
    for field in [
        "email",
        "phone",
        "birthdate",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "grade",
        "allergies",
    ]:
        value = data.get(field)
        if value and not getattr(person, field):
            setattr(person, field, value)
            changed = True
    if changed:
        person.save()
    return person


def _ensure_person(
    first_name,
    last_name,
    email="",
    phone="",
    birthdate=None,
    create_if_missing=True,
    **extra,
):
    person = _match_person(email, first_name, last_name, birthdate, phone)
    if person:
        return _apply_contact_data(
            person,
            {
                "email": email,
                "phone": phone,
                "birthdate": birthdate,
                "address_line1": extra.get("address_line1"),
                "address_line2": extra.get("address_line2"),
                "city": extra.get("city"),
                "state": extra.get("state"),
                "postal_code": extra.get("postal_code"),
                "grade": extra.get("grade"),
                "allergies": extra.get("allergies"),
            },
        )
    if not create_if_missing:
        return None
    return Person.objects.create(
        first_name=first_name or "Friend",
        last_name=last_name or "of AnchorPoint",
        email=email,
        phone=phone,
        birthdate=birthdate,
        address_line1=extra.get("address_line1"),
        address_line2=extra.get("address_line2"),
        city=extra.get("city"),
        state=extra.get("state"),
        postal_code=extra.get("postal_code"),
        grade=extra.get("grade"),
        allergies=extra.get("allergies"),
    )


def _ensure_household(primary: Person, dependent: Person) -> Optional[Household]:
    existing = Household.objects.filter(members=primary).first()
    if not existing:
        household_name = f"{primary.last_name or primary.first_name} Household".strip()
        existing = Household.objects.create(
            name=household_name or f"Household {primary.pk}",
            primary_adult=primary,
            address_line1=primary.address_line1,
            address_line2=primary.address_line2,
            city=primary.city,
            state=primary.state,
            postal_code=primary.postal_code,
        )
    HouseholdMember.objects.get_or_create(
        household=existing,
        person=primary,
        defaults={"relationship_type": HouseholdMember.RelationshipType.ADULT},
    )
    HouseholdMember.objects.get_or_create(
        household=existing,
        person=dependent,
        defaults={"relationship_type": HouseholdMember.RelationshipType.CHILD},
    )
    return existing


def _mark_attendee_matched(
    attendee,
    person: Person,
    matched_by=None,
    notes="",
):
    attendee.person = person
    attendee.match_status = EventRegistrationAttendee.MATCH_STATUS_MATCHED
    attendee.matched_at = timezone.now()
    if matched_by:
        attendee.matched_by = matched_by
    if notes:
        attendee.match_notes = notes
    group = enroll_person_in_event_group(attendee.event, person)
    update_fields = [
        "person",
        "match_status",
        "matched_at",
        "matched_by",
        "match_notes",
        "updated_at",
    ]
    if group and attendee.group_id != group.id:
        attendee.group = group
        update_fields.append("group")
    attendee.save(update_fields=update_fields)


@transaction.atomic
def match_registration_attendees(registration: EventRegistration):
    contact_person = _ensure_person(
        registration.first_name,
        registration.last_name,
        email=registration.email,
        phone=registration.phone,
        birthdate=registration.birthdate,
        address_line1=registration.address_line1,
        address_line2=registration.address_line2,
        city=registration.city,
        state=registration.state,
        postal_code=registration.postal_code,
    )
    for attendee in registration.attendees.all():
        person = _ensure_person(
            attendee.first_name,
            attendee.last_name,
            email=attendee.email,
            phone=attendee.phone,
            birthdate=attendee.birthdate,
            address_line1=attendee.address_line1 or registration.address_line1,
            address_line2=attendee.address_line2 or registration.address_line2,
            city=attendee.city or registration.city,
            state=attendee.state or registration.state,
            postal_code=attendee.postal_code or registration.postal_code,
            grade=attendee.grade,
            allergies=attendee.allergies,
            create_if_missing=False,
        )
        if not person:
            attendee.match_status = EventRegistrationAttendee.MATCH_STATUS_PENDING
            attendee.save(update_fields=["match_status", "updated_at"])
            continue

        _mark_attendee_matched(attendee, person)

        guardian = None
        if attendee.parent_guardian_email:
            g_first, g_last = _split_name(attendee.parent_guardian_name)
            guardian = _ensure_person(
                g_first or registration.first_name,
                g_last or registration.last_name,
                email=attendee.parent_guardian_email,
                phone=attendee.parent_guardian_phone,
            )
        elif attendee.parent_guardian_name:
            g_first, g_last = _split_name(attendee.parent_guardian_name)
            guardian = _ensure_person(
                g_first or registration.first_name,
                g_last or registration.last_name,
                email=registration.email,
                phone=attendee.parent_guardian_phone or registration.phone,
            )
        elif attendee.is_minor:
            guardian = contact_person

        if guardian and guardian != person:
            _ensure_household(guardian, person)


def manually_assign_attendee(attendee, person, matched_by=None, notes=""):
    _mark_attendee_matched(attendee, person, matched_by=matched_by, notes=notes)


def create_person_from_attendee(attendee):
    return Person.objects.create(
        first_name=attendee.first_name or "Friend",
        last_name=attendee.last_name or "of AnchorPoint",
        email=attendee.email,
        phone=attendee.phone,
        birthdate=attendee.birthdate,
        address_line1=attendee.address_line1,
        address_line2=attendee.address_line2,
        city=attendee.city,
        state=attendee.state,
        postal_code=attendee.postal_code,
        grade=attendee.grade,
        allergies=attendee.allergies,
    )


def link_guardian_household(guardian: Person, dependent: Person):
    if guardian and dependent and guardian != dependent:
        _ensure_household(guardian, dependent)


def ensure_event_group(event) -> Optional[Group]:
    if not event:
        return None
    if event.registration_group:
        return event.registration_group
    name = f"{event.title} ({event.pk})"
    group, _ = Group.objects.get_or_create(
        name=name,
        defaults={
            "category": "event",
            "description": f"Attendees for {event.title}",
            "meeting_schedule": "Event-specific",
        },
    )
    if event.registration_group_id != group.id:
        event.registration_group = group
        event.save(update_fields=["registration_group"])
    return group


def enroll_person_in_event_group(event, person):
    if not person or not event:
        return None
    group = ensure_event_group(event)
    if not group:
        return None
    GroupMembership.objects.get_or_create(group=group, person=person)
    return group
