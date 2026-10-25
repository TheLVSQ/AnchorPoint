"""
Tests for check-in label printing.

All tests use mocks/SimpleTestCase — no database required.
The kiosk view integration tests live in test_kiosk_views.py.
"""

from datetime import date
from unittest import TestCase as SimpleTestCase
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase as DjangoSimpleTestCase

from checkin.models import CheckInSession, Room
from checkin.services.label_generator import LabelGenerator
from people.models import Person


def _make_session(print_emergency_phone=False):
    """Lightweight mock session for label generation."""
    session = MagicMock(spec=CheckInSession)
    session.name = "Sunday Service"
    session.date = date(2026, 5, 11)
    session.print_emergency_phone = print_emergency_phone
    return session


def _make_checkin_mock(first_name="Alice", last_name="Smith", room_name="Room 1",
                       security_code="ABCD", allergies="", custody_flag=False,
                       grade="", grade_display="", custody_notes="", is_minor=False):
    """Mock CheckIn with all fields needed for label generation."""
    person = MagicMock(spec=Person)
    person.first_name = first_name
    person.last_name = last_name
    person.allergies = allergies
    person.custody_flag = custody_flag
    person.custody_notes = custody_notes
    person.grade = grade
    person.is_minor = is_minor
    person.get_grade_display = lambda: grade_display
    person.households = MagicMock()

    room = MagicMock(spec=Room)
    room.name = room_name

    checkin = MagicMock()
    checkin.person = person
    checkin.room = room
    checkin.security_code = security_code
    return checkin


class LabelGeneratorTests(DjangoSimpleTestCase):
    def test_build_label_set_returns_child_plus_pickup(self):
        checkin = _make_checkin_mock()
        images = LabelGenerator.build_label_set([checkin], _make_session())
        # 1 child label + 1 pickup tag
        self.assertEqual(len(images), 2)

    def test_build_label_set_two_children(self):
        c1 = _make_checkin_mock("Alice", "Smith", security_code="ABCD")
        c2 = _make_checkin_mock("Bob", "Smith", security_code="ABCD")
        images = LabelGenerator.build_label_set([c1, c2], _make_session())
        # 2 child labels + 1 pickup tag
        self.assertEqual(len(images), 3)

    def test_child_label_is_landscape_898x600(self):
        images = LabelGenerator.build_label_set([_make_checkin_mock()], _make_session())
        self.assertEqual(images[0].size, (898, 600))  # 76mm x 51mm

    def test_pickup_tag_is_landscape_898x600(self):
        images = LabelGenerator.build_label_set([_make_checkin_mock()], _make_session())
        self.assertEqual(images[-1].size, (898, 600))

    def test_returns_pil_images(self):
        from PIL import Image
        images = LabelGenerator.build_label_set([_make_checkin_mock()], _make_session())
        for img in images:
            self.assertIsInstance(img, Image.Image)

    def test_empty_checkins_returns_empty_list(self):
        self.assertEqual(LabelGenerator.build_label_set([], None), [])

    def test_no_session_does_not_raise(self):
        images = LabelGenerator.build_label_set([_make_checkin_mock()], None)
        self.assertEqual(len(images), 2)
