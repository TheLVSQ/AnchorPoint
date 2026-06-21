from datetime import time

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import CheckInConfiguration, CheckInSession
from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person


class AutoEnrollTests(TestCase):
    """A check-in config can auto-add anyone who checks in to a chosen group."""

    def setUp(self):
        self.group = Group.objects.create(name="VBS 2026", category="event")
        self.config = CheckInConfiguration.objects.create(
            name="VBS", auto_enroll_group=self.group
        )
        self.session = CheckInSession.objects.create(
            configuration=self.config, name="VBS Day 1", date=timezone.localdate(),
            checkin_opens=time(0, 0), checkin_closes=time(23, 50),
            event_starts=time(0, 5), event_ends=time(23, 55), is_active=True,
        )
        self.fam = Household.objects.create(name="New Family")
        self.kid = Person.objects.create(first_name="Walk", last_name="In")
        HouseholdMember.objects.create(
            household=self.fam, person=self.kid,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )

    def _unlock(self):
        s = self.client.session
        s["kiosk_authenticated"] = True
        s["kiosk_session_id"] = self.session.pk
        s.save()

    def test_default_is_none(self):
        self.assertIsNone(CheckInConfiguration.objects.create(name="Plain").auto_enroll_group)

    def test_checkin_auto_enrolls(self):
        self._unlock()
        resp = self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.fam.pk]),
            {f"select_{self.kid.pk}": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            GroupMembership.objects.filter(group=self.group, person=self.kid).exists()
        )

    def test_idempotent_when_already_member(self):
        GroupMembership.objects.create(group=self.group, person=self.kid)
        self._unlock()
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.fam.pk]),
            {f"select_{self.kid.pk}": "on"},
        )
        self.assertEqual(
            GroupMembership.objects.filter(group=self.group, person=self.kid).count(), 1
        )

    def test_no_group_no_enroll(self):
        self.config.auto_enroll_group = None
        self.config.save()
        self._unlock()
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.fam.pk]),
            {f"select_{self.kid.pk}": "on"},
        )
        self.assertFalse(GroupMembership.objects.filter(person=self.kid).exists())
