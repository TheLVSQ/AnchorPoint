"""Read-only audit: registration attendees linked to a Person that looks like someone else.

Run on prod (changes nothing):
  cd /home/deploy/anchorpoint/docker && \
    docker compose exec -T web python manage.py shell < ../scripts/audit_person_matches.py

Prints IDs and first names only.
"""
from events.models import EventRegistrationAttendee as A

matched = A.objects.filter(match_status=A.MATCH_STATUS_MATCHED, person__isnull=False).select_related("person")
name_mismatch, bday_mismatch, minor_to_adult = [], [], []
for a in matched:
    p = a.person
    how = "manual" if a.matched_by_id else "auto"
    if (a.first_name or "").strip().lower() != (p.first_name or "").strip().lower():
        name_mismatch.append(f"attendee {a.pk} {a.first_name!r} -> person {p.pk} {p.first_name!r} ({how})")
    if a.birthdate and p.birthdate and a.birthdate != p.birthdate:
        bday_mismatch.append(f"attendee {a.pk} -> person {p.pk} ({how})")
    if a.is_minor and p.age is not None and p.age >= 18:
        minor_to_adult.append(f"attendee {a.pk} {a.first_name!r} -> person {p.pk} {p.first_name!r} age {p.age} ({how})")

print("matched attendees:", matched.count())
for title, rows in (("first name differs", name_mismatch), ("birthdate differs", bday_mismatch),
                    ("minor attendee linked to an adult", minor_to_adult)):
    print(f"{title}: {len(rows)}")
    for row in rows[:30]:
        print("   ", row)
