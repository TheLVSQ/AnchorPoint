"""Read-only: what did each wrong auto-match (child attached to an adult) change?

Run on prod (changes nothing):
  ssh ... 'cd /home/deploy/anchorpoint/docker && docker compose exec -T web python manage.py shell' \
    < scripts/audit_bad_matches_detail.py

Prints IDs, first names and yes/no flags only (no allergy text, no contact details).
"""
from checkin.models import CheckIn
from events.models import EventRegistrationAttendee as A
from groups.models import GroupMembership
from people.models import Person


def same_first(a, p):
    return (a.first_name or "").strip().lower() == (p.first_name or "").strip().lower()


bad = [
    a for a in A.objects.filter(match_status=A.MATCH_STATUS_MATCHED, person__isnull=False,
                                matched_by__isnull=True)
    .select_related("person", "event", "registration")
    if not same_first(a, a.person)
]
print(f"wrong auto-matches: {len(bad)}\n")
for a in bad:
    p, ev = a.person, a.event
    legit_here = A.objects.filter(event=ev, person=p).exclude(pk=a.pk)
    legit_here = [x.pk for x in legit_here if same_first(x, p)]
    in_group = bool(ev.registration_group_id) and GroupMembership.objects.filter(
        group_id=ev.registration_group_id, person=p).exists()
    child_records = list(Person.objects.filter(
        first_name__iexact=a.first_name, last_name__iexact=a.last_name).values_list("pk", flat=True))
    checkins = CheckIn.objects.filter(person=p, checked_in_at__date__gte=a.registration.created_at.date()).count()
    print(f"attendee {a.pk} {a.first_name!r} (event {ev.pk} {ev.title!r}) -> person {p.pk} {p.first_name!r} age {p.age}")
    print(f"    adult has a grade: {bool(p.grade)}"
          f"{' (same as child: ' + str(p.grade == a.grade) + ')' if p.grade else ''}")
    print(f"    adult allergies contain child's: "
          f"{bool(a.allergies) and (a.allergies.strip().lower() in (p.allergies or '').lower())}")
    print(f"    adult in event group: {in_group}; adult is also a real attendee of this event: {legit_here or 'no'}")
    print(f"    adult check-ins since registration: {checkins}")
    print(f"    separate record(s) for the child by name: {child_records or 'none'}")
    print()
