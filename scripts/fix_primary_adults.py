"""Families whose primary adult breaks the rule (must be an ADULT MEMBER, or blank).

Read-only report by default; with FIX_COMMIT=1 it applies the households.membership
rule to just those families: keep a valid primary, else the longest-standing adult
member, else blank. Self-contained, so it works before or after the deploy.

  ssh ... 'cd /home/deploy/anchorpoint/docker && docker compose exec -T web python manage.py shell' \
    < scripts/fix_primary_adults.py
  # then, to apply:
  ssh ... '... docker compose exec -T -e FIX_COMMIT=1 web python manage.py shell' < scripts/fix_primary_adults.py

Prints family/person IDs and first names only.
"""
import os

from django.db import transaction

from households.models import Household, HouseholdMember

COMMIT = os.environ.get("FIX_COMMIT") == "1"
ADULT = HouseholdMember.RelationshipType.ADULT

problems = []
for h in Household.objects.exclude(primary_adult__isnull=True).select_related("primary_adult"):
    role = (HouseholdMember.objects.filter(household=h, person_id=h.primary_adult_id)
            .values_list("relationship_type", flat=True).first())
    if role == ADULT:
        continue
    why = "not a member" if role is None else f"is a member as {role!r}"
    first = (HouseholdMember.objects.filter(household=h, relationship_type=ADULT)
             .order_by("pk").select_related("person").first())
    problems.append((h, why, first.person if first else None))

print(f"families with an invalid primary adult: {len(problems)}")
for h, why, new in problems:
    print(f"  family {h.pk} {h.name!r}: primary #{h.primary_adult_id} "
          f"{h.primary_adult.first_name!r} {why} -> "
          f"{f'#{new.pk} {new.first_name!r}' if new else 'blank'}")

if problems:
    print("COMMITTING" if COMMIT else "DRY RUN (set FIX_COMMIT=1 to apply)")
    with transaction.atomic():
        for h, _why, new in problems:
            Household.objects.filter(pk=h.pk).update(primary_adult=new)
        if not COMMIT:
            transaction.set_rollback(True)
    print("done" if COMMIT else "nothing was written")
