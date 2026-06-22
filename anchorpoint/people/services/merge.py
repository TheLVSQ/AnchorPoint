"""Merge duplicate Person / Household records.

Re-points every related row (check-ins, household + group memberships, event
registrations, comms, primary-adult refs) from the duplicate onto the survivor,
fills the survivor's blank fields from the duplicate (never overwriting), then
deletes the duplicate. Each merge is atomic. Group memberships and grade carry
over, so a merged VBS child keeps their eligibility / roster spot.
"""

from django.db import IntegrityError, transaction

from households.models import HouseholdMember

# Survivor's *blank* scalar fields get filled from the duplicate (we never
# overwrite a value the survivor already has).
_FILL_FIELDS = [
    "email", "phone", "birthdate", "grade", "gender", "marital_status",
    "allergies", "security_notes", "notes",
    "address_line1", "address_line2", "city", "state", "postal_code",
    "salvation_date", "baptism_date", "first_visit_date",
    "custody_notes", "unauthorized_pickup",
    "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship",
]


def _repoint_relations(obj, survivor):
    """Move every reverse FK/O2O row from `obj` onto `survivor`. When a unique
    constraint means the survivor already has the equivalent row (e.g. the same
    group membership), drop the duplicate's row instead of re-pointing it."""
    for rel in obj._meta.related_objects:
        if rel.many_to_many:
            continue  # the through model's own FK relation covers this
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

    changed = []
    for f in _FILL_FIELDS:
        if not getattr(survivor, f, None) and getattr(duplicate, f, None):
            setattr(survivor, f, getattr(duplicate, f))
            changed.append(f)
    if not survivor.custody_flag and duplicate.custody_flag:
        survivor.custody_flag = True
        changed.append("custody_flag")
    if survivor.photo_consent == "unknown" and duplicate.photo_consent != "unknown":
        survivor.photo_consent = duplicate.photo_consent
        changed.append("photo_consent")
    if changed:
        survivor.save()

    _repoint_relations(duplicate, survivor)
    duplicate.delete()
    return survivor


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

    duplicate.delete()  # cascades its membership rows (members already on canonical)
    return canonical
