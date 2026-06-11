from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone

from checkin.models import CheckInConfiguration, CheckInSession, CheckInWindow, Room
from checkin.services.session_manager import get_or_create_session


class SessionManagerTests(TestCase):
    def setUp(self):
        self.config = CheckInConfiguration.objects.create(
            name="Sunday Kids", location_name="Main Building"
        )
        self.room = Room.objects.create(name="Room 100")
        self.config.rooms.add(self.room)
        now = timezone.localtime()
        self.window = CheckInWindow.objects.create(
            configuration=self.config,
            schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=(now.weekday() + 1) % 7,
            checkin_opens=time(0, 0),
            event_starts=time(0, 5),
            checkin_closes=time(23, 50),
            event_ends=time(23, 55),
        )

    def test_creates_session_when_none_exists(self):
        session = get_or_create_session(self.config, self.window)
        self.assertIsNotNone(session)
        self.assertEqual(session.configuration, self.config)
        self.assertEqual(session.window, self.window)
        self.assertEqual(session.date, timezone.localdate())
        self.assertIn(self.room, session.rooms.all())

    def test_returns_existing_session(self):
        session1 = get_or_create_session(self.config, self.window)
        session2 = get_or_create_session(self.config, self.window)
        self.assertEqual(session1.pk, session2.pk)

    def test_session_copies_times_from_window(self):
        session = get_or_create_session(self.config, self.window)
        self.assertEqual(session.checkin_opens, self.window.checkin_opens)
        self.assertEqual(session.checkin_closes, self.window.checkin_closes)
        self.assertEqual(session.event_starts, self.window.event_starts)
        self.assertEqual(session.event_ends, self.window.event_ends)

    def test_session_name_from_config(self):
        session = get_or_create_session(self.config, self.window)
        self.assertEqual(session.name, "Sunday Kids")
