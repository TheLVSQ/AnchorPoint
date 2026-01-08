from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import OrganizationSettings
from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person

from .forms import CheckInWindowFormSet
from .models import AttendanceRecord, CheckInConfiguration, CheckInWindow


class CheckInConfigurationModelTests(TestCase):
    def test_schedule_summary_formats_windows(self):
        config = CheckInConfiguration.objects.create(
            name="Kids Check-In",
            welcome_message="Welcome families!",
            location_name="North Lobby",
        )
        CheckInWindow.objects.create(
            configuration=config,
            schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=0,
            opens_at=time(8, 30),
            closes_at=time(10, 0),
        )
        summary = config.schedule_summary()
        self.assertIn("Sunday", summary)
        self.assertIn("8:30 AM", summary)
        self.assertIn("10:00 AM", summary)

    def test_schedule_summary_handles_specific_dates(self):
        config = CheckInConfiguration.objects.create(name="Camp Check-In")
        CheckInWindow.objects.create(
            configuration=config,
            schedule_type=CheckInWindow.TYPE_SPECIFIC_DATE,
            specific_date="2025-01-04",
            opens_at=time(9, 0),
            closes_at=time(11, 0),
        )
        summary = config.schedule_summary()
        self.assertIn("Jan", summary)
        self.assertIn("2025", summary)
        self.assertIn("9:00 AM", summary)


class CheckInConfigurationViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="staff",
            password="password",
        )
        self.group = Group.objects.create(
            name="Elementary",
            category="checkin",
        )
        self.formset_prefix = CheckInWindowFormSet(instance=CheckInConfiguration()).prefix

    def _window_management_data(self, total_forms="1", initial_forms="0"):
        return {
            f"{self.formset_prefix}-TOTAL_FORMS": total_forms,
            f"{self.formset_prefix}-INITIAL_FORMS": initial_forms,
            f"{self.formset_prefix}-MIN_NUM_FORMS": "1",
            f"{self.formset_prefix}-MAX_NUM_FORMS": "1000",
        }

    def test_configuration_creation_flow(self):
        self.client.force_login(self.user)
        url = reverse("attendance:configuration_create")
        post_data = {
            "name": "Kids Check-In",
            "location_name": "Lobby A",
            "welcome_message": "We're glad you're here!",
            "description": "Covers nursery through 5th grade.",
            "is_active": "on",
            "groups": [str(self.group.pk)],
            f"{self.formset_prefix}-0-schedule_type": CheckInWindow.TYPE_WEEKLY,
            f"{self.formset_prefix}-0-day_of_week": "0",
            f"{self.formset_prefix}-0-opens_at": "08:30",
            f"{self.formset_prefix}-0-closes_at": "10:30",
            f"{self.formset_prefix}-0-is_active": "on",
            f"{self.formset_prefix}-0-notes": "Early service",
        }
        post_data.update(self._window_management_data())
        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        config = CheckInConfiguration.objects.get(name="Kids Check-In")
        self.assertEqual(config.groups.count(), 1)
        window = config.windows.get()
        self.assertEqual(window.day_of_week, 0)
        self.assertEqual(window.opens_at, time(8, 30))
        self.assertEqual(window.closes_at, time(10, 30))

    def test_configuration_creation_specific_date_window(self):
        self.client.force_login(self.user)
        url = reverse("attendance:configuration_create")
        post_data = {
            "name": "Special Event",
            "location_name": "Gym",
            "is_active": "on",
            "groups": [str(self.group.pk)],
            f"{self.formset_prefix}-0-schedule_type": CheckInWindow.TYPE_SPECIFIC_DATE,
            f"{self.formset_prefix}-0-specific_date": "2025-01-04",
            f"{self.formset_prefix}-0-opens_at": "09:00",
            f"{self.formset_prefix}-0-closes_at": "11:00",
            f"{self.formset_prefix}-0-is_active": "on",
        }
        post_data.update(self._window_management_data())
        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        config = CheckInConfiguration.objects.get(name="Special Event")
        window = config.windows.get()
        self.assertEqual(window.schedule_type, CheckInWindow.TYPE_SPECIFIC_DATE)
        self.assertEqual(str(window.specific_date), "2025-01-04")

    def test_configuration_list_view_requires_login(self):
        response = self.client.get(reverse("attendance:configuration_list"))
        self.assertEqual(response.status_code, 302)

    def test_configuration_list_renders_program(self):
        self.client.force_login(self.user)
        config = CheckInConfiguration.objects.create(
            name="Elementary Program",
            welcome_message="Hi friends!",
        )
        config.groups.add(self.group)
        CheckInWindow.objects.create(
            configuration=config,
            schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=2,
            opens_at=time(18, 0),
            closes_at=time(19, 30),
        )
        response = self.client.get(reverse("attendance:configuration_list"))
        self.assertContains(response, "Elementary Program")
        self.assertContains(response, "Hi friends!")
        self.assertContains(response, "Tuesday")


class KioskFlowTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="Primary", category="checkin")
        self.config = CheckInConfiguration.objects.create(name="Kids", is_active=True)
        self.config.groups.add(self.group)
        now = timezone.localtime()
        self.window = CheckInWindow.objects.create(
            configuration=self.config,
            schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=now.weekday(),
            opens_at=(now - timedelta(hours=1)).time(),
            closes_at=(now + timedelta(hours=1)).time(),
        )
        self.household = Household.objects.create(name="Smith Family", phone="417-555-9988")
        self.child = Person.objects.create(first_name="Ava", last_name="Smith")
        HouseholdMember.objects.create(household=self.household, person=self.child, relationship_type="child")
        GroupMembership.objects.create(group=self.group, person=self.child)
        settings_instance = OrganizationSettings.load()
        settings_instance.kiosk_pin = "1234"
        settings_instance.save()

    def _unlock(self):
        session = self.client.session
        session["kiosk_authenticated"] = True
        session.save()

    def test_kiosk_unlock_flow(self):
        response = self.client.post(
            reverse("attendance:kiosk_unlock"),
            {"pin": "1234"},
        )
        self.assertRedirects(response, reverse("attendance:kiosk_lookup"))

    def test_lookup_requires_pin(self):
        response = self.client.get(reverse("attendance:kiosk_lookup"))
        self.assertRedirects(response, reverse("attendance:kiosk_unlock"))

    def test_lookup_lists_family_when_unlocked(self):
        self._unlock()
        response = self.client.get(reverse("attendance:kiosk_lookup"), {"query": "Smith"})
        self.assertContains(response, "Smith Family")
        self.assertContains(response, "Select family")

    def test_family_selection_creates_attendance(self):
        self._unlock()
        response = self.client.post(
            reverse("attendance:kiosk_family_select", args=[self.household.pk]),
            {
                "person_ids": [str(self.child.id)],
                "window_id": str(self.window.id),
            },
        )
        self.assertRedirects(response, reverse("attendance:kiosk_confirmation"))
        record = AttendanceRecord.objects.get(person=self.child)
        self.assertEqual(record.configuration, self.config)

    def test_confirmation_displays_records(self):
        self._unlock()
        record = AttendanceRecord.objects.create(
            person=self.child,
            household=self.household,
            group=self.group,
            configuration=self.config,
            checkin_window=self.window,
        )
        session = self.client.session
        session["kiosk_confirmation_records"] = [record.id]
        session.save()
        response = self.client.get(reverse("attendance:kiosk_confirmation"))
        self.assertContains(response, "Ava Smith")
