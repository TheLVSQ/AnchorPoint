"""Nightly hygiene detection, the Data cleanup queue, and merge safety."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from checkin.models import CheckIn, CheckInSession
from core.models import UserProfile
from households import hygiene
from households.models import CleanupFinding, FamilyConflictFlag, Household, HouseholdMember
from people.models import Person
from people.services.merge import MergeBlocked, merge_households, merge_persons

F = CleanupFinding
ADULT = HouseholdMember.RelationshipType.ADULT
CHILD = HouseholdMember.RelationshipType.CHILD


def _family(name, *members, **fields):
    h = Household.objects.create(name=name, **fields)
    for person, role in members:
        HouseholdMember.objects.create(household=h, person=person, relationship_type=role)
    return h


def _keys(kind=None):
    qs = F.objects.filter(status=F.STATUS_OPEN)
    if kind:
        qs = qs.filter(kind=kind)
    return set(qs.values_list("key", flat=True))


class DuplicatePeopleDetectionTests(TestCase):
    def test_same_name_and_phone_is_flagged(self):
        a = Person.objects.create(first_name="Casey", last_name="Reed", phone="(555) 123-4567")
        b = Person.objects.create(first_name=" casey", last_name="REED", phone="555.123.4567")
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_PERSON), {f"person:{a.pk}:{b.pk}"})

    def test_twins_are_not_flagged(self):
        mom = Person.objects.create(first_name="Dana", last_name="Lee", phone="5550001111")
        t1 = Person.objects.create(first_name="Ava", last_name="Lee", birthdate=date(2017, 1, 1),
                                   phone="5550001111", email="lee@example.com")
        t2 = Person.objects.create(first_name="Ella", last_name="Lee", birthdate=date(2017, 1, 1),
                                   phone="5550001111", email="lee@example.com")
        _family("Lee Family", (mom, ADULT), (t1, CHILD), (t2, CHILD))
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_PERSON), set())

    def test_jr_and_sr_with_different_birthdates_are_not_flagged(self):
        sr = Person.objects.create(first_name="John", last_name="Hale", birthdate=date(1960, 5, 1),
                                   phone="5552223333", address_line1="1 Elm St", postal_code="12345")
        jr = Person.objects.create(first_name="John", last_name="Hale", birthdate=date(1990, 5, 1),
                                   phone="5552223333", address_line1="1 Elm St", postal_code="12345")
        _family("Hale Family", (sr, ADULT), (jr, ADULT))
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_PERSON), set())

    def test_parent_and_child_sharing_email_and_phone_are_not_flagged(self):
        Person.objects.create(first_name="Sam", last_name="Ortiz", email="ortiz@example.com", phone="5554445555")
        Person.objects.create(first_name="Mia", last_name="Ortiz", email="ortiz@example.com", phone="5554445555")
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_PERSON), set())

    def test_same_name_alone_is_not_enough(self):
        Person.objects.create(first_name="John", last_name="Smith")
        Person.objects.create(first_name="John", last_name="Smith")
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_PERSON), set())

    def test_new_last_name_needs_two_signals(self):
        a = Person.objects.create(first_name="Kara", last_name="Bell", email="kara@example.com",
                                  birthdate=date(1985, 2, 2))
        b = Person.objects.create(first_name="Kara", last_name="Bell-Owens", email="KARA@example.com")
        c = Person.objects.create(first_name="Kara", last_name="Owens", email="kara@example.com",
                                  birthdate=date(1985, 2, 2))
        hygiene.run()
        # b shares only email with the others (1 signal) → no pair; a+c share email + birthdate.
        self.assertEqual(_keys(F.KIND_DUPLICATE_PERSON), {f"person:{a.pk}:{c.pk}"})
        self.assertNotIn(b.pk, {f.person_a_id for f in F.objects.all()} | {f.person_b_id for f in F.objects.all()})


class HouseholdDetectionTests(TestCase):
    def test_same_address_flags_families(self):
        a = _family("Kline", address_line1="12 Oak St.", postal_code="12345-0001")
        b = _family("Kline Family", address_line1="12  oak st", postal_code="12345")
        hygiene.run()
        self.assertIn(f"household:{a.pk}:{b.pk}", _keys(F.KIND_DUPLICATE_HOUSEHOLD))

    def test_same_surname_alone_is_not_a_duplicate(self):
        _family("Morris Family", address_line1="1 A St", postal_code="11111")
        _family("Morris Family", address_line1="2 B St", postal_code="11111")
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_HOUSEHOLD), set())

    def test_different_external_ids_never_pair(self):
        _family("Smith", external_id="rock-fam:1", phone="5559998888")
        _family("Smith", external_id="rock-fam:2", phone="5559998888")
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_HOUSEHOLD), set())

    def test_shared_custody_child_is_not_a_signal(self):
        kid = Person.objects.create(first_name="Noah", last_name="Grant")
        mom = Person.objects.create(first_name="Erin", last_name="Grant")
        dad = Person.objects.create(first_name="Paul", last_name="Grant")
        _family("Grant Family", (mom, ADULT), (kid, CHILD))
        _family("Grant Family", (dad, ADULT), (kid, CHILD))
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_HOUSEHOLD), set())

    def test_same_name_and_shared_adult_is_flagged(self):
        mom = Person.objects.create(first_name="Erin", last_name="Grant")
        a = _family("Grant Family", (mom, ADULT))
        b = _family("grant family", (mom, ADULT))
        hygiene.run()
        self.assertEqual(_keys(F.KIND_DUPLICATE_HOUSEHOLD), {f"household:{a.pk}:{b.pk}"})

    def test_orphans(self):
        empty = _family("Ghost Family")
        kid = Person.objects.create(first_name="Liam", last_name="Fox", birthdate=date(2016, 1, 1))
        kids_only = _family("Fox Family", (kid, CHILD))
        grown = Person.objects.create(first_name="Ana", last_name="Diaz", birthdate=date(1980, 1, 1))
        _family("Diaz Family", (grown, CHILD))  # adult by age even with a child role
        hygiene.run()
        self.assertEqual(_keys(F.KIND_EMPTY_HOUSEHOLD), {f"empty:{empty.pk}"})
        self.assertEqual(_keys(F.KIND_NO_ADULT_HOUSEHOLD), {f"noadult:{kids_only.pk}"})


class QueueLifecycleTests(TestCase):
    def test_rerun_is_idempotent_and_dismissed_stays_dismissed(self):
        _family("Ghost Family")
        hygiene.run()
        hygiene.run()
        self.assertEqual(F.objects.count(), 1)
        finding = F.objects.get()
        hygiene.resolve(finding, None, F.STATUS_DISMISSED, "OK as-is")
        hygiene.run()
        finding.refresh_from_db()
        self.assertEqual(finding.status, F.STATUS_DISMISSED)

    def test_finding_that_stops_matching_auto_resolves_and_can_reopen(self):
        h = _family("Ghost Family")
        hygiene.run()
        p = Person.objects.create(first_name="Al", last_name="Ghost", birthdate=date(1970, 1, 1))
        HouseholdMember.objects.create(household=h, person=p, relationship_type=ADULT)
        counts = hygiene.run()
        self.assertEqual(counts["resolved"], 1)
        self.assertEqual(F.objects.get().status, F.STATUS_RESOLVED)
        HouseholdMember.objects.all().delete()
        hygiene.run()
        self.assertEqual(F.objects.get().status, F.STATUS_OPEN)

    def test_command_dry_run_saves_nothing_and_prints_no_names(self):
        _family("Secret Family")
        from io import StringIO
        out = StringIO()
        call_command("family_hygiene", "--dry-run", stdout=out)
        self.assertEqual(F.objects.count(), 0)
        self.assertIn("Family with no members: 1", out.getvalue())
        self.assertNotIn("Secret", out.getvalue())


class MergeSafetyTests(TestCase):
    def test_safety_text_is_combined_not_dropped(self):
        keep = Person.objects.create(first_name="Zoe", last_name="Park", allergies="Peanuts",
                                     custody_notes="Mom only")
        dup = Person.objects.create(first_name="Zoe", last_name="Park", allergies="Bees",
                                    custody_notes="mom only", unauthorized_pickup="Uncle Ray")
        merge_persons(keep, dup)
        keep.refresh_from_db()
        self.assertEqual(keep.allergies, "Peanuts\nBees")
        self.assertEqual(keep.custody_notes, "Mom only")  # same text, not doubled
        self.assertEqual(keep.unauthorized_pickup, "Uncle Ray")

    def test_two_logins_block_the_merge(self):
        User = get_user_model()
        a = Person.objects.create(first_name="Tim", last_name="Ng")
        b = Person.objects.create(first_name="Tim", last_name="Ng")
        for i, p in enumerate((a, b)):
            u = User.objects.create_user(username=f"tim{i}", password="pw")
            u.profile.person = p
            u.profile.save()
        with self.assertRaises(MergeBlocked):
            merge_persons(a, b)
        self.assertEqual(UserProfile.objects.filter(person__isnull=False).count(), 2)

    def test_household_merge_keeps_flags_and_checkins(self):
        kid = Person.objects.create(first_name="Ivy", last_name="Cole")
        keep = _family("Cole")
        dup = _family("Cole", (kid, CHILD))
        flag = FamilyConflictFlag.objects.create(child=kid, household=dup)
        session = CheckInSession.objects.create(
            name="Sun", date=date(2026, 10, 18), checkin_opens=time(9), checkin_closes=time(12),
            event_starts=time(9, 30), event_ends=time(11),
        )
        CheckIn.objects.create(session=session, person=kid, security_code="IVY1")
        merge_households(keep, dup)
        flag.refresh_from_db()
        self.assertEqual(flag.household, keep)
        self.assertEqual(CheckIn.objects.get().person, kid)
        self.assertEqual(list(keep.members.all()), [kid])


class CleanupViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="adm", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.staff = User.objects.create_user(username="stf", password="pw")
        self.staff.profile.role = UserProfile.Role.STAFF
        self.staff.profile.save()

    def _dupes(self):
        a = Person.objects.create(first_name="Pete", last_name="Price", phone="5551112222")
        b = Person.objects.create(first_name="Pete", last_name="Price", phone="5551112222", grade="3")
        session = CheckInSession.objects.create(
            name="VBS", date=date(2026, 6, 22), checkin_opens=time(9), checkin_closes=time(12),
            event_starts=time(9, 30), event_ends=time(11),
        )
        CheckIn.objects.create(session=session, person=b, security_code="DUP1")
        hygiene.run()
        return a, b, F.objects.get(kind=F.KIND_DUPLICATE_PERSON)

    def test_staff_get_403_admin_sees_page_and_badge(self):
        self._dupes()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("households:cleanup_list")).status_code, 403)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("households:cleanup_list"))
        self.assertContains(resp, "Pete Price / Pete Price")
        self.assertContains(resp, "Keep this one")
        self.assertEqual(resp.context["cleanup_open"], 1)

    def test_staff_cannot_merge(self):
        a, b, finding = self._dupes()
        self.client.force_login(self.staff)
        resp = self.client.post(reverse("households:cleanup_merge", args=[finding.pk]), {"keep": a.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Person.objects.count(), 2)

    def test_merge_keeps_chosen_record_and_history(self):
        a, b, finding = self._dupes()
        self.client.force_login(self.admin)
        self.client.post(reverse("households:cleanup_merge", args=[finding.pk]), {"keep": a.pk})
        self.assertEqual(list(Person.objects.values_list("pk", flat=True)), [a.pk])
        a.refresh_from_db()
        self.assertEqual(a.grade, "3")
        self.assertEqual(CheckIn.objects.get().person, a)
        finding.refresh_from_db()
        self.assertEqual(finding.status, F.STATUS_RESOLVED)
        self.assertIn("Merged", finding.resolution)
        # The page still renders with one side gone.
        resp = self.client.get(reverse("households:cleanup_list") + "?show=resolved")
        self.assertEqual(resp.status_code, 200)

    def test_keep_must_be_one_of_the_pair(self):
        a, b, finding = self._dupes()
        other = Person.objects.create(first_name="X", last_name="Y")
        self.client.force_login(self.admin)
        self.client.post(reverse("households:cleanup_merge", args=[finding.pk]), {"keep": other.pk})
        self.assertEqual(Person.objects.count(), 3)

    def test_dismiss_and_offsite_next_is_ignored(self):
        _, _, finding = self._dupes()
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("households:cleanup_dismiss", args=[finding.pk]),
                                {"next": "https://evil.example/"})
        self.assertEqual(resp.url, reverse("households:cleanup_list"))
        finding.refresh_from_db()
        self.assertEqual(finding.status, F.STATUS_DISMISSED)

    def test_delete_empty_family_only_if_still_empty(self):
        h = _family("Ghost Family")
        hygiene.run()
        finding = F.objects.get(kind=F.KIND_EMPTY_HOUSEHOLD)
        p = Person.objects.create(first_name="Late", last_name="Joiner")
        HouseholdMember.objects.create(household=h, person=p)
        self.client.force_login(self.admin)
        self.client.post(reverse("households:cleanup_delete_household", args=[finding.pk]))
        self.assertTrue(Household.objects.filter(pk=h.pk).exists())
        HouseholdMember.objects.all().delete()
        hygiene.run()
        finding = F.objects.get(kind=F.KIND_EMPTY_HOUSEHOLD, status=F.STATUS_OPEN)
        self.client.post(reverse("households:cleanup_delete_household", args=[finding.pk]))
        self.assertFalse(Household.objects.filter(pk=h.pk).exists())
