"""Merge duplicate Person / Household records.

Re-points every related row (check-ins, household + group memberships, event
registrations, comms, primary-adult refs) from the duplicate onto the survivor,
fills the survivor's blank fields from the duplicate (never overwriting), then
deletes the duplicate. Each merge is atomic. Group memberships and grade carry
over, so a merged VBS child keeps their eligibility / roster spot.
"""

from django.db import IntegrityError, transaction

from households.models import HouseholdMember
from people.services import identity


class MergeBlocked(Exception):
    """The pair can't be merged safely (shown to the admin as-is)."""

# Cleanup findings point at the records being merged; they're re-evaluated
# after a merge rather than carried across (that could pair a record with itself).
_SKIP_REPOINT = {"households.CleanupFinding"}


def _repoint_relations(obj, survivor):
    """Move every reverse FK/O2O row from `obj` onto `survivor`. When a unique
    constraint means the survivor already has the equivalent row (e.g. the same
    group membership), drop the duplicate's row instead of re-pointing it."""
    # include_hidden: related_name="+" FKs (e.g. FamilyConflictFlag.guardian)
    # aren't in `related_objects` but still point at this record.
    for rel in obj._meta.get_fields(include_hidden=True):
        if not (rel.auto_created and not rel.concrete) or rel.many_to_many:
            continue  # only reverse FK/O2O; the through model's FK covers M2M
        if rel.related_model._meta.label in _SKIP_REPOINT:
            continue
        fk = rel.field.name
        related = rel.related_model
        for pk in list(related._base_manager.filter(**{fk: obj}).values_list("pk", flat=True)):
            try:
                with transaction.atomic():
                    related._base_manager.filter(pk=pk).update(**{fk: survivor})
            except IntegrityError:
                related._base_manager.filter(pk=pk).delete()


@transaction.atomic
def merge_persons(survivor, duplicate):
    """Merge `duplicate` Person into `survivor` and delete the duplicate."""
    if survivor.pk == duplicate.pk:
        return survivor
    if _has_login(survivor) and _has_login(duplicate):
        raise MergeBlocked(
            f"Both {survivor} records have their own login. Remove one login "
            "(Admin → Users) before merging."
        )

    # Same rule as every intake path: fill blanks, ADD safety/notes text (dropping a
    # duplicate's allergy or custody note would be a check-in safety gap).
    identity.absorb(survivor, {
        f: getattr(duplicate, f, None)
        for f in identity.FILL_FIELDS + identity.APPEND_FIELDS + ["custody_flag", "photo_consent"]
    })

    _repoint_relations(duplicate, survivor)
    duplicate.delete()
    return survivor


def _has_login(person):
    from core.models import UserProfile
    return UserProfile.objects.filter(person=person).exists()


@transaction.atomic
def merge_households(canonical, duplicate):
    """Merge `duplicate` Household into `canonical`: move members, keep the
    canonical's primary adult (or adopt the duplicate's), fill blank contact
    fields, then delete the now-redundant duplicate."""
    if canonical.pk == duplicate.pk:
        return canonical

    for m in list(duplicate.memberships.select_related("person").all()):
        HouseholdMember.objects.get_or_create(
            household=canonical, person=m.person,
            defaults={"relationship_type": m.relationship_type},
        )
    if not canonical.primary_adult_id and duplicate.primary_adult_id:
        canonical.primary_adult_id = duplicate.primary_adult_id
    for f in ["phone", "address_line1", "address_line2", "city", "state", "postal_code"]:
        if not getattr(canonical, f, None) and getattr(duplicate, f, None):
            setattr(canonical, f, getattr(duplicate, f))
    canonical.save()

    # Anything else pointing at the duplicate (e.g. family-safety flags) follows it.
    _repoint_relations(duplicate, canonical)
    duplicate.delete()
    return canonical
