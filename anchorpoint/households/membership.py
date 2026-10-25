"""Family membership: who is in which family, in what role, and who the primary adult
is (GLOSSARY.md). Every in-app membership change goes through here.

Interface:

- ``add_member(household, person, role)``
- ``remove_member(household, person)``
- ``move_member(person, source, target, role=None, keep_in_source=False)``
- ``set_role(household, person, role)``
- ``set_primary(household, person)``
- ``create_family(name="", adult=None, **fields)``
- ``link_guardian(guardian, child, registration=None)``
- ``family_surname(household)``

Rules kept here:
- The primary adult is always an ADULT MEMBER of the family, or blank. When the primary
  leaves or stops being an adult, the longest-standing other adult takes over (or it
  goes blank); a family with no primary gets its first adult as primary.
- A role is always given explicitly: a forgotten role must never make a child an adult
  (adults get pickup-code texts and are listed as guardians).
- New families are named "{Surname} Family".
- Families with no adult are allowed (imports and registrations create children first);
  the nightly cleanup flags them.
"""
from django.db import IntegrityError, transaction

from .models import Household, HouseholdMember

Role = HouseholdMember.RelationshipType
ADULT = Role.ADULT


class MembershipError(Exception):
    """A change that would break a family rule. The message is shown to staff."""


@transaction.atomic
def add_member(household, person, role) -> bool:
    """Add ``person`` with ``role``; True if newly added (an existing membership is left
    as it is)."""
    role = _valid_role(role)
    _, created = HouseholdMember.objects.get_or_create(
        household=household, person=person, defaults={"relationship_type": role}
    )
    _repair_primary(household)
    return created


@transaction.atomic
def remove_member(household, person):
    HouseholdMember.objects.filter(household=household, person=person).delete()
    _repair_primary(household)


@transaction.atomic
def move_member(person, source, target, *, role=None, keep_in_source=False) -> bool:
    """Add ``person`` to ``target`` (keeping their role unless ``role`` is given) and,
    unless ``keep_in_source``, take them out of ``source``. False if they were already in
    ``target`` (nothing changes then)."""
    current = HouseholdMember.objects.filter(household=source, person=person).first()
    role = _valid_role(role or (current.relationship_type if current else None))
    try:
        with transaction.atomic():
            HouseholdMember.objects.create(household=target, person=person, relationship_type=role)
    except IntegrityError:
        return False
    _repair_primary(target)
    if not keep_in_source:
        remove_member(source, person)
    return True


@transaction.atomic
def set_role(household, person, role):
    role = _valid_role(role)
    updated = HouseholdMember.objects.filter(household=household, person=person).update(
        relationship_type=role
    )
    if not updated:
        raise MembershipError(f"{person} isn't in {household.name}.")
    _repair_primary(household)


def set_primary(household, person):
    if person is None:
        raise MembershipError("Choose an adult in the family.")
    if not HouseholdMember.objects.filter(
        household=household, person=person, relationship_type=ADULT
    ).exists():
        raise MembershipError(
            f"{person} can't be the primary adult: the primary adult must be an adult "
            f"member of {household.name}."
        )
    if household.primary_adult_id != person.pk:
        household.primary_adult = person
        household.save(update_fields=["primary_adult"])


@transaction.atomic
def create_family(*, name="", adult=None, **fields) -> Household:
    """A new family named ``name`` or "{Surname} Family"; ``adult`` (if given) joins as
    an adult and becomes primary. ``fields`` are Household fields (phone, address...)."""
    fields.pop("primary_adult", None)  # always derived from membership
    surname = (adult.last_name or adult.first_name).strip() if adult else ""
    household = Household.objects.create(
        name=(name or "").strip() or (f"{surname} Family" if surname else "New Family"),
        **fields,
    )
    if adult is not None:
        add_member(household, adult, ADULT)
    return household


@transaction.atomic
def link_guardian(guardian, child, *, registration=None, filled_fields=None, raise_flag=True):
    """Put ``child`` (as a Child) in ``guardian``'s family, creating one for the
    guardian if they have none. If the child already belongs to a family the guardian
    isn't in, the link is still made but a family-safety flag is raised for staff
    review (``raise_flag=False`` for staff bulk imports). Returns the family, or None
    if guardian and child are the same person."""
    from .family_flags import conflicting_households, record_registration_conflict

    if guardian is None or child is None or guardian.pk == child.pk:
        return None
    prior = conflicting_households(child, guardian) if raise_flag else []
    household = Household.objects.filter(members=guardian).order_by("pk").first()
    if household is None:
        household = create_family(
            adult=guardian,
            address_line1=guardian.address_line1, address_line2=guardian.address_line2,
            city=guardian.city, state=guardian.state, postal_code=guardian.postal_code,
        )
    else:
        add_member(household, guardian, ADULT)  # no-op if already a member
    already_in = HouseholdMember.objects.filter(household=household, person=child).exists()
    add_member(household, child, Role.CHILD)
    if prior:
        record_registration_conflict(
            child=child, guardian=guardian, household=household,
            added_membership=not already_in, prior_households=prior,
            filled_fields=filled_fields or {}, registration=registration,
        )
    return household


def family_surname(household) -> str:
    """Best surname for a new member: the primary adult's, else the first adult's,
    else any member's, else the family name minus "Family"/"Household"."""
    people = [household.primary_adult] if household.primary_adult_id else []
    people += [m.person for m in household.memberships.select_related("person")
               .order_by("relationship_type", "pk")]  # "adult" sorts first
    for person in people:
        if person and (person.last_name or "").strip():
            return person.last_name.strip()
    name = (household.name or "").strip()
    for suffix in (" Family", " Household"):
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name or "Guest"


# --------------------------------------------------------------------------- internals


def _valid_role(role):
    if role not in Role.values:
        raise MembershipError("Choose a role: Adult, Child, Student or Other.")
    return role


def _repair_primary(household):
    """Keep the primary adult an adult member: keep a valid one, else promote the
    longest-standing adult member, else blank."""
    adults = HouseholdMember.objects.filter(household=household, relationship_type=ADULT)
    if household.primary_adult_id and adults.filter(person_id=household.primary_adult_id).exists():
        return
    first = adults.order_by("pk").values_list("person_id", flat=True).first()
    if household.primary_adult_id != first:
        Household.objects.filter(pk=household.pk).update(primary_adult_id=first)
        household.primary_adult_id = first
        if hasattr(household, "_state"):
            household._state.fields_cache.pop("primary_adult", None)
