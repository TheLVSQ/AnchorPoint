from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from groups.models import Group, GroupMembership
from households.family_flags import conflicting_households, record_registration_conflict
from households.models import Household, HouseholdMember
from people.models import Person
from people.services import identity

from .models import EventRegistration, EventRegistrationAttendee


def _split_name(full_name: str) -> Tuple[str, str]:
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _ensure_person(first_name, last_name, email="", phone="", birthdate=None, **extra):
    """Find this person (people.services.identity) and absorb what's new, else create."""
    first_name, last_name = (first_name or "").strip(), (last_name or "").strip()
    fields = {k: v for k, v in extra.items() if v not in (None, "")}
    if not first_name:  # can't safely match a nameless record; create a placeholder
        return Person.objects.create(
            first_name="Friend", last_name=last_name or "of AnchorPoint",
            email=email or None, phone=phone or None, birthdate=birthdate, **fields,
        )
    person, _match = identity.find_or_create(
        identity.Incoming(first_name, last_name or "of AnchorPoint", email or "", phone or "", birthdate),
        fields,
    )
    return person


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
    family = contact_person.households.all()
    for attendee in registration.attendees.all():
        match = identity.find_person(
            identity.Incoming(
                attendee.first_name, attendee.last_name, attendee.email or "",
                attendee.phone or "", attendee.birthdate,
            ),
            family=family,
        )
        if not match:
            attendee.match_status = EventRegistrationAttendee.MATCH_STATUS_PENDING
            attendee.save(update_fields=["match_status", "updated_at"])
            continue
        person = match.person
        changes = identity.absorb(person, {
            "email": attendee.email,
            "phone": attendee.phone,
            "birthdate": attendee.birthdate,
            "address_line1": attendee.address_line1 or registration.address_line1,
            "address_line2": attendee.address_line2 or registration.address_line2,
            "city": attendee.city or registration.city,
            "state": attendee.state or registration.state,
            "postal_code": attendee.postal_code or registration.postal_code,
            "grade": attendee.grade,
            "allergies": attendee.allergies,
        })
        # Only fields that were blank go on a family-safety flag: undo blanks them, and
        # it must never wipe text the person already had (e.g. an allergy note).
        filled = {
            f: str(getattr(person, f)) for f, kind in changes.items() if kind == identity.FILLED
        }

        _mark_attendee_matched(attendee, person, notes=f"Auto-matched by {match.matched_by}")

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
            prior = conflicting_households(person, guardian)
            prior_ids = set(Household.objects.filter(members=person).values_list("pk", flat=True))
            household = _ensure_household(guardian, person)
            if prior:
                # Child already in a family the guardian isn't part of: keep the
                # link (honest re-registrations shouldn't stall) but flag it.
                record_registration_conflict(
                    child=person,
                    guardian=guardian,
                    household=household,
                    added_membership=household is not None and household.pk not in prior_ids,
                    prior_households=prior,
                    filled_fields=filled,
                    registration=registration,
                )


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


def find_guardian(attendee):
    """The existing guardian for a minor attendee (staff match queue), or None. Uses the
    guardian's name if given, else the registrant's, with the guardian/registrant
    email and phone; same identity rules as everything else."""
    registration = attendee.registration
    first, last = _split_name(attendee.parent_guardian_name)
    if not first:
        first, last = registration.first_name, registration.last_name
    match = identity.find_person(identity.Incoming(
        first, last,
        email=attendee.parent_guardian_email or registration.email or "",
        phone=attendee.parent_guardian_phone or registration.phone or "",
    ))
    return match.person if match else None


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
