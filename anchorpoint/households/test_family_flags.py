"""Family-safety flags: child already in one family linked to another."""
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import OrganizationSettings, UserProfile
from events.models import Event, EventRegistration, EventRegistrationAttendee
from events.services import match_registration_attendees
from households.family_flags import alert_flagged_checkins
from households.models import FamilyConflictFlag, Household, HouseholdMember
from people.models import Person


def _user(username, role, email=None, phone=""):
    user = get_user_model().objects.create_user(
        username=username, password="pw", email=email or f"{username}@example.com",
    )
    user.profile.role = role
    user.profile.phone_number = phone
    user.profile.save()
    return user


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class FamilyFlagTests(TestCase):
    def setUp(self):
        self.recipient = _user("safety", UserProfile.Role.STAFF, phone="555-0100")
        org = OrganizationSettings.load()
        org.family_alert_recipients.add(self.recipient)

        self.family = Household.objects.create(name="Parent Family")
        self.mom = Person.objects.create(first_name="Pat", last_name="Parent",
                                         email="pat@example.com")
        self.kid = Person.objects.create(first_name="Kim", last_name="Parent",
                                         birthdate=date(2016, 4, 4))
        HouseholdMember.objects.create(household=self.family, person=self.mom,
                                       relationship_type=HouseholdMember.RelationshipType.ADULT)
        HouseholdMember.objects.create(household=self.family, person=self.kid,
                                       relationship_type=HouseholdMember.RelationshipType.CHILD)
        self.event = Event.objects.create(title="VBS", summary="s", description="d")
        mail.outbox.clear()  # drop the welcome email from creating the user

    def _register(self, guardian_name, guardian_email, guardian_phone="555-9999"):
        reg = EventRegistration.objects.create(
            event=self.event, first_name=guardian_name.split()[0],
            last_name=guardian_name.split()[-1], email=guardian_email,
            phone=guardian_phone, address_line1="1 Elsewhere Rd",
        )
        EventRegistrationAttendee.objects.create(
            registration=reg, event=self.event, first_name="Kim", last_name="Parent",
            birthdate=date(2016, 4, 4), is_minor=True, phone=guardian_phone,
            parent_guardian_name=guardian_name, parent_guardian_email=guardian_email,
            parent_guardian_phone=guardian_phone, allergies="peanuts",
        )
        match_registration_attendees(reg)
        return reg

    def test_outside_guardian_raises_flag_and_emails_recipient(self):
        self._register("Evil Person", "evil@example.com")
        flag = FamilyConflictFlag.objects.get()
        self.assertEqual(flag.child, self.kid)
        self.assertEqual(flag.existing_households, "Parent Family")
        self.assertTrue(flag.added_membership)
        self.assertIn("phone", flag.filled_fields)
        self.assertIn("allergies", flag.filled_fields)
        # "Apply now, just alert": the link is in place.
        self.assertTrue(HouseholdMember.objects.filter(household=flag.household,
                                                       person=self.kid).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.recipient.email, mail.outbox[0].to)
        self.assertIn("Kim Parent", mail.outbox[0].subject)

    def test_guardian_already_in_family_is_not_flagged(self):
        self._register("Pat Parent", "pat@example.com")
        self.assertFalse(FamilyConflictFlag.objects.exists())

    def test_child_with_no_family_is_not_flagged(self):
        HouseholdMember.objects.filter(person=self.kid).delete()
        self._register("New Parent", "new@example.com")
        self.assertFalse(FamilyConflictFlag.objects.exists())

    def test_undo_removes_link_and_clears_filled_fields(self):
        self._register("Evil Person", "evil@example.com")
        flag = FamilyConflictFlag.objects.get()
        self.client.force_login(self.recipient)
        self.client.post(reverse("households:family_flag_undo", args=[flag.pk]))
        flag.refresh_from_db()
        self.kid.refresh_from_db()
        self.assertEqual(flag.status, FamilyConflictFlag.STATUS_UNDONE)
        self.assertEqual(flag.resolved_by, self.recipient)
        self.assertFalse(HouseholdMember.objects.filter(household=flag.household,
                                                        person=self.kid).exists())
        self.assertTrue(HouseholdMember.objects.filter(household=self.family,
                                                       person=self.kid).exists())
        self.assertFalse(self.kid.phone)
        self.assertFalse(self.kid.allergies)

    def test_undo_keeps_fields_staff_changed_since(self):
        self._register("Evil Person", "evil@example.com")
        flag = FamilyConflictFlag.objects.get()
        self.kid.refresh_from_db()
        self.kid.allergies = "shellfish (confirmed by mom)"
        self.kid.save()
        self.client.force_login(self.recipient)
        self.client.post(reverse("households:family_flag_undo", args=[flag.pk]))
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.allergies, "shellfish (confirmed by mom)")

    def test_mark_reviewed_keeps_link(self):
        self._register("Step Parent", "step@example.com")
        flag = FamilyConflictFlag.objects.get()
        self.client.force_login(self.recipient)
        self.client.post(reverse("households:family_flag_reviewed", args=[flag.pk]))
        flag.refresh_from_db()
        self.assertEqual(flag.status, FamilyConflictFlag.STATUS_REVIEWED)
        self.assertTrue(HouseholdMember.objects.filter(household=flag.household,
                                                       person=self.kid).exists())

    def test_badge_shown_to_recipient_not_to_other_staff(self):
        self._register("Evil Person", "evil@example.com")
        self.client.force_login(self.recipient)
        resp = self.client.get(reverse("people_list"))
        self.assertContains(resp, reverse("households:family_flags"))
        self.client.force_login(_user("otherstaff", UserProfile.Role.STAFF))
        resp = self.client.get(reverse("people_list"))
        self.assertNotContains(resp, reverse("households:family_flags"))

    def test_review_page_staff_only(self):
        self.client.force_login(_user("va", UserProfile.Role.VOLUNTEER_ADMIN))
        self.assertEqual(self.client.get(reverse("households:family_flags")).status_code, 403)

    @mock.patch("messaging.services.TwilioService")
    def test_kiosk_checkin_of_flagged_child_emails_and_texts_once_per_session(self, twilio):
        from datetime import time
        from django.utils import timezone
        from checkin.models import CheckIn, CheckInSession
        self._register("Evil Person", "evil@example.com")
        mail.outbox.clear()
        session = CheckInSession.objects.create(
            name="Sunday", date=timezone.localdate(), checkin_opens=time(0, 0),
            checkin_closes=time(23, 50), event_starts=time(0, 5), event_ends=time(23, 55),
        )
        ci = CheckIn.objects.create(session=session, person=self.kid, security_code="ABCD",
                                    arrived_at=timezone.now())
        sent = alert_flagged_checkins([ci], session)
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("checked in", mail.outbox[0].subject)
        twilio.return_value.send_sms.assert_called_once()
        self.assertEqual(twilio.return_value.send_sms.call_args[0][0], "555-0100")
        # Same session again: no duplicate alert.
        self.assertEqual(alert_flagged_checkins([ci], session), 0)
        self.assertEqual(len(mail.outbox), 1)
