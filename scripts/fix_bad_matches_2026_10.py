"""One-off fix (2026-10-25): undo 10 registration auto-matches that put a child on an
adult's (or sibling's) record via a shared email/phone. See PR #123 and the output of
scripts/audit_bad_matches_detail.py.

DRY RUN by default: prints every change, writes nothing. To apply, set FIX_COMMIT=1:
  ssh ... 'cd /home/deploy/anchorpoint/docker && docker compose exec -T -e FIX_COMMIT=1 web python manage.py shell' \
    < scripts/fix_bad_matches_2026_10.py

Before changing anything it verifies every row is still exactly as audited; if any
check fails it stops and changes nothing. Safe to re-run (already-fixed rows fail the
"still on the wrong record" check, so a second run stops without writing).

Not done here (needs a person, see the checklist in PR #123): Hannah #118's birthdate,
grade and allergies; Bethany #161's grade; Kayla #2920's allergy note; Leeanne #2921's
birthdate typo.
"""
import os

from django.db import transaction
from django.utils import timezone

from events.models import EventRegistrationAttendee as A
from groups.models import GroupMembership
from people.models import Person

COMMIT = os.environ.get("FIX_COMMIT") == "1"
STAMP = timezone.localdate().isoformat()

# attendee id -> the person it was wrongly matched to
WRONG = {3: 161, 12: 118, 11: 118, 13: 118, 4: 2921, 7: 2922, 8: 2922, 5: 129, 2: 2920, 1: 2920}
# attendee id -> the child's own existing record
RELINK = {3: 162, 12: 2927, 11: 119, 13: 121, 7: 2870, 8: 2871, 5: 1916, 2: 2926, 1: 2925}
# attendees with no record of their own: back to the staff match queue
REQUEUE = [4]
# clearly-adult records whose grade came from a child
CLEAR_GRADE = [2922, 129, 2920]


def same(a, b):
    return (a or "").strip().lower() == (b or "").strip().lower()


problems = []
attendees = {a.pk: a for a in A.objects.filter(pk__in=WRONG).select_related("event", "person")}
for aid, wrong_pid in WRONG.items():
    a = attendees.get(aid)
    if a is None:
        problems.append(f"attendee {aid}: not found")
    elif a.person_id != wrong_pid or a.matched_by_id is not None:
        problems.append(f"attendee {aid}: no longer auto-matched to #{wrong_pid} (now #{a.person_id})")
children = Person.objects.in_bulk(list(RELINK.values()))
for aid, cid in RELINK.items():
    a, c = attendees.get(aid), children.get(cid)
    if c is None:
        problems.append(f"child record #{cid}: not found")
    elif a and not (same(a.first_name, c.first_name) and same(a.last_name, c.last_name)):
        problems.append(f"attendee {aid} {a.first_name} {a.last_name} != record #{cid} "
                        f"{c.first_name} {c.last_name}")
for pid in CLEAR_GRADE:
    p = Person.objects.filter(pk=pid).first()
    if p is None or p.age is None or p.age < 18:
        problems.append(f"person #{pid}: not clearly an adult (age {p.age if p else '?'}); not clearing grade")

if problems:
    print("STOPPED, nothing changed:")
    for msg in problems:
        print("  -", msg)
    raise SystemExit

print("COMMITTING" if COMMIT else "DRY RUN (set FIX_COMMIT=1 to apply)")
with transaction.atomic():
    touched_groups = set()
    for aid, wrong_pid in WRONG.items():
        a = attendees[aid]
        note = f"{STAMP}: auto-match had put this child on #{wrong_pid} (shared family email/phone)."
        group_id = a.event.registration_group_id
        if aid in RELINK:
            child = children[RELINK[aid]]
            a.person = child
            a.match_notes = (a.match_notes + "\n" if a.match_notes else "") + f"Re-linked to #{child.pk}. {note}"
            a.save(update_fields=["person", "match_notes", "updated_at"])
            print(f"attendee {aid} {a.first_name}: #{wrong_pid} -> #{child.pk}")
            if group_id:
                _, added = GroupMembership.objects.get_or_create(group_id=group_id, person=child)
                if added:
                    print(f"    + #{child.pk} added to event group {group_id}")
        else:
            a.person = None
            a.match_status = A.MATCH_STATUS_PENDING
            a.match_notes = (a.match_notes + "\n" if a.match_notes else "") + f"Sent back to the queue. {note}"
            a.save(update_fields=["person", "match_status", "match_notes", "updated_at"])
            print(f"attendee {aid} {a.first_name}: unlinked from #{wrong_pid} -> staff match queue")
        if group_id:
            touched_groups.add((group_id, a.event_id, wrong_pid))

    # Remove a wrongly-matched person from the event group only if no attendee of that
    # event is (now) genuinely them.
    for group_id, event_id, pid in sorted(touched_groups):
        if A.objects.filter(event_id=event_id, person_id=pid).exists():
            print(f"    keep #{pid} in event group {group_id} (still a real attendee)")
            continue
        n, _ = GroupMembership.objects.filter(group_id=group_id, person_id=pid).delete()
        if n:
            print(f"    - #{pid} removed from event group {group_id}")

    for pid in CLEAR_GRADE:
        p = Person.objects.get(pk=pid)
        if p.grade:
            print(f"person #{pid} {p.first_name} (age {p.age}): grade {p.grade!r} cleared")
            p.grade = None
            p.save(update_fields=["grade"])

    if not COMMIT:
        transaction.set_rollback(True)
print("done" if COMMIT else "dry run finished; nothing was written")
