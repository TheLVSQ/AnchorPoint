"""Person identity: the matching order, its safety rules, and absorbing incoming data."""
from datetime import date
from unittest import mock

from django.test import TestCase

from events.models import Event, EventRegistration, EventRegistrationAttendee
from events.services import match_registration_attendees
from households.models import Household, HouseholdMember
from people.models import Person
from people.services import identity
from people.services.identity import Incoming, find_person
from people.services.merge import merge_persons


def _person(first, last="Walker", **kw):
    return Person.objects.create(first_name=first, last_name=last, **kw)


class PhoneRuleTests(TestCase):
    def test_last_ten_digits(self):
        self.assertTrue(identity.same_phone("+1 (555) 123-4567", "555.123.4567"))
        self.assertEqual(identity.phone_key("15551234567"), "5551234567")

    def test_short_numbers_never_match(self):
        self.assertEqual(identity.phone_key("123-4567"), "")
        self.assertFalse(identity.same_phone("123-4567", "123-4567"))
        self.assertFalse(identity.same_phone("", ""))


class LadderTests(TestCase):
    def setUp(self):
        self.sue = _person("Sue", email="sue@example.com", phone="+15550101234",
                           birthdate=date(1988, 1, 1))

    def test_external_id_wins_without_name(self):
        self.sue.external_id = "rock:1"
        self.sue.save()
        match = find_person(Incoming("Different", external_id="rock:1"))
        self.assertEqual((match.person, match.matched_by), (self.sue, "external id"))

    def test_email_with_first_name(self):
        match = find_person(Incoming("sue", "Whoever", email="SUE@example.com"))
        self.assertEqual((match.person, match.matched_by), (self.sue, "email"))

    def test_name_and_birthdate(self):
        match = find_person(Incoming("Sue", "Walker", birthdate=date(1988, 1, 1)))
        self.assertEqual(match.matched_by, "name + birthdate")

    def test_phone_with_first_name_any_format(self):
        match = find_person(Incoming("Sue", phone="555-010-1234"))
        self.assertEqual((match.person, match.matched_by), (self.sue, "phone"))

    def test_family_step_needs_family_and_last_name(self):
        family = Household.objects.create(name="Walker Family")
        ava = _person("Ava")
        HouseholdMember.objects.create(household=family, person=ava)
        self.assertIsNone(find_person(Incoming("Ava", "Walker")))  # no family given
        match = find_person(Incoming("Ava", "Walker"), family=family)
        self.assertEqual((match.person, match.matched_by), (ava, "family"))
        self.assertIsNone(find_person(Incoming("Ava", "Walker"),
                                      family=Household.objects.filter(name="Other")))

    def test_no_first_name_never_matches(self):
        self.assertIsNone(find_person(Incoming("", email="sue@example.com")))


class SafetyRuleTests(TestCase):
    """A wrong match puts one person's data on another, so these all refuse."""

    def setUp(self):
        self.mom = _person("Sue", email="family@example.com", phone="+15550101234",
                           birthdate=date(1988, 1, 1))

    def test_child_with_parents_email_is_not_the_parent(self):
        self.assertIsNone(find_person(Incoming("Ava", "Walker", email="family@example.com")))

    def test_child_with_parents_phone_is_not_the_parent(self):
        self.assertIsNone(find_person(Incoming("Ava", "Walker", phone="5550101234")))

    def test_different_birthdate_rules_out(self):
        # Same first name + same family email, but a different birthdate: Sue Jr.
        self.assertIsNone(find_person(
            Incoming("Sue", "Walker", email="family@example.com", birthdate=date(2015, 5, 5))
        ))

    def test_unknown_birthdate_on_record_does_not_veto(self):
        self.mom.birthdate = None
        self.mom.save()
        match = find_person(Incoming("Sue", email="family@example.com", birthdate=date(1988, 1, 1)))
        self.assertEqual(match.person, self.mom)

    def test_two_candidates_is_unknown_not_a_guess(self):
        _person("Sue", email="family@example.com")  # e.g. a duplicate record
        self.assertIsNone(find_person(Incoming("Sue", email="family@example.com")))

    def test_ambiguous_step_stops_rather_than_falling_through(self):
        _person("Sue", email="family@example.com")
        # Phone alone would pick one, but the email step was already ambiguous.
        self.assertIsNone(find_person(
            Incoming("Sue", email="family@example.com", phone="5550101234")
        ))


class AbsorbTests(TestCase):
    def test_fills_blanks_never_overwrites(self):
        p = _person("Ava", grade="3")
        changes = identity.absorb(p, {"grade": "4", "city": "Bolivar", "email": ""})
        p.refresh_from_db()
        self.assertEqual((p.grade, p.city), ("3", "Bolivar"))
        self.assertEqual(changes, {"city": identity.FILLED})

    def test_safety_text_is_added_to_not_dropped(self):
        p = _person("Ava", allergies="Bees")
        changes = identity.absorb(p, {"allergies": "Peanuts"})
        p.refresh_from_db()
        self.assertEqual(p.allergies, "Bees\nPeanuts")
        self.assertEqual(changes, {"allergies": identity.APPENDED})

    def test_same_safety_text_not_duplicated(self):
        p = _person("Ava", allergies="Bees")
        self.assertEqual(identity.absorb(p, {"allergies": "bees"}), {})

    def test_custody_flag_and_photo_consent(self):
        p = _person("Ava", photo_consent="denied")
        changes = identity.absorb(p, {"custody_flag": True, "photo_consent": "granted"})
        p.refresh_from_db()
        self.assertTrue(p.custody_flag)
        self.assertEqual(p.photo_consent, "denied")  # only set while unknown
        self.assertEqual(changes, {"custody_flag": identity.FILLED})

    def test_merge_uses_the_same_rule(self):
        keep = _person("Ava", allergies="Bees")
        dupe = _person("Ava", allergies="Peanuts", city="Bolivar")
        merge_persons(keep, dupe)
        keep.refresh_from_db()
        self.assertEqual((keep.allergies, keep.city), ("Bees\nPeanuts", "Bolivar"))


class FindOrCreateTests(TestCase):
    def test_creates_when_unknown(self):
        person, match = identity.find_or_create(Incoming("Ava", "Walker"), {"grade": "3"})
        self.assertIsNone(match)
        self.assertEqual((person.first_name, person.grade), ("Ava", "3"))

    def test_absorbs_when_matched(self):
        sue = _person("Sue", email="sue@example.com")
        person, match = identity.find_or_create(
            Incoming("Sue", "Walker", email="sue@example.com", phone="5550101234")
        )
        self.assertEqual((person, match.matched_by), (sue, "email"))
        sue.refresh_from_db()
        self.assertEqual(sue.phone, "5550101234")


class RegistrationMatchingTests(TestCase):
    """The original bug: a child registered with a parent's email/phone became the parent."""

    def setUp(self):
        self.mom = _person("Sue", email="sue@example.com", phone="+15550101234",
                           allergies="Penicillin")
        self.event = Event.objects.create(title="VBS", summary="s", description="d")

    def _register(self, **attendee):
        reg = EventRegistration.objects.create(
            event=self.event, first_name="Sue", last_name="Walker",
            email="sue@example.com", phone="555-010-1234",
        )
        a = EventRegistrationAttendee.objects.create(
            registration=reg, event=self.event, **attendee
        )
        with mock.patch("events.services.record_registration_conflict"):
            match_registration_attendees(reg)
        a.refresh_from_db()
        return a

    def test_child_with_parent_contact_goes_to_queue(self):
        a = self._register(first_name="Ava", last_name="Walker", email="sue@example.com",
                           phone="555-010-1234", allergies="Peanuts")
        self.assertEqual(a.match_status, EventRegistrationAttendee.MATCH_STATUS_PENDING)
        self.mom.refresh_from_db()
        self.assertEqual(self.mom.allergies, "Penicillin")  # untouched

    def test_auto_match_records_why(self):
        a = self._register(first_name="Sue", last_name="Walker", email="sue@example.com")
        self.assertEqual(a.person, self.mom)
        self.assertEqual(a.match_notes, "Auto-matched by email")

    def test_known_child_matched_inside_registrants_family(self):
        family = Household.objects.create(name="Walker Family")
        ava = _person("Ava")
        for p in (self.mom, ava):
            HouseholdMember.objects.create(household=family, person=p)
        a = self._register(first_name="Ava", last_name="Walker", allergies="Peanuts")
        self.assertEqual(a.person, ava)
        ava.refresh_from_db()
        self.assertEqual(ava.allergies, "Peanuts")
