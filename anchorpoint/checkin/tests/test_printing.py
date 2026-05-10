"""
Tests for check-in label printing.

All tests use mocks/SimpleTestCase — no database required.
The kiosk view integration tests live in test_kiosk_views.py.
"""

from datetime import date
from unittest import TestCase as SimpleTestCase
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase as DjangoSimpleTestCase

from checkin.models import CheckInSession, PrinterConfiguration, Room
from checkin.services.label_generator import LabelGenerator
from checkin.services.print_service import PrintService
from people.models import Person


def _make_session():
    """Lightweight mock session for label generation."""
    session = MagicMock(spec=CheckInSession)
    session.name = "Sunday Service"
    session.date = date(2026, 5, 11)
    return session


def _make_checkin_mock(first_name="Alice", last_name="Smith", room_name="Room 1",
                       security_code="ABCD", allergies="", custody_flag=False):
    """Mock CheckIn with all fields needed for label generation."""
    person = MagicMock(spec=Person)
    person.first_name = first_name
    person.last_name = last_name
    person.allergies = allergies
    person.custody_flag = custody_flag

    room = MagicMock(spec=Room)
    room.name = room_name

    checkin = MagicMock()
    checkin.person = person
    checkin.room = room
    checkin.security_code = security_code
    return checkin


def _make_printer_config(**kwargs):
    """Create an unsaved PrinterConfiguration instance for unit tests."""
    defaults = dict(
        name="Test QL",
        printer_type="brother_ql",
        host="192.168.1.100",
        port=9100,
        ql_model="QL-800",
        is_active=True,
        is_default=True,
    )
    defaults.update(kwargs)
    return PrinterConfiguration(**defaults)


# =============================================================================
# Label Generator Tests  (no DB)
# =============================================================================

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

    def test_child_label_width_is_696(self):
        images = LabelGenerator.build_label_set([_make_checkin_mock()], _make_session())
        self.assertEqual(images[0].width, 696)

    def test_pickup_tag_width_is_696(self):
        images = LabelGenerator.build_label_set([_make_checkin_mock()], _make_session())
        self.assertEqual(images[-1].width, 696)

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


# =============================================================================
# PrintService Tests  (no DB — uses unsaved model instances + mocks)
# =============================================================================

class PrintServiceTests(DjangoSimpleTestCase):
    def test_print_checkins_returns_false_when_no_printer_configured(self):
        # Explicitly pass None — simulates no active printer in DB
        with patch.object(PrinterConfiguration.objects.__class__, "filter", return_value=MagicMock(first=MagicMock(return_value=None))):
            service = PrintService(None)
        self.assertFalse(service.print_checkins([], None))

    def test_print_checkins_returns_false_when_checkins_empty(self):
        config = _make_printer_config()
        service = PrintService(config)
        mock_adapter = MagicMock()
        with patch("checkin.services.print_service.get_printer_adapter", return_value=mock_adapter):
            result = service.print_checkins([], None)
        self.assertFalse(result)

    def test_print_checkins_calls_adapter_print_images(self):
        checkin = _make_checkin_mock()
        session = _make_session()
        mock_adapter = MagicMock()
        mock_adapter.print_images.return_value = True
        service = PrintService(_make_printer_config())

        with patch("checkin.services.print_service.get_printer_adapter", return_value=mock_adapter):
            result = service.print_checkins([checkin], session)

        self.assertTrue(result)
        mock_adapter.print_images.assert_called_once()
        images_arg = mock_adapter.print_images.call_args[0][0]
        # 1 child label + 1 pickup tag
        self.assertEqual(len(images_arg), 2)

    def test_print_checkins_returns_false_on_adapter_exception(self):
        checkin = _make_checkin_mock("Bob", "Jones")
        session = _make_session()
        mock_adapter = MagicMock()
        mock_adapter.print_images.side_effect = RuntimeError("printer offline")
        service = PrintService(_make_printer_config())

        with patch("checkin.services.print_service.get_printer_adapter", return_value=mock_adapter):
            result = service.print_checkins([checkin], session)

        self.assertFalse(result)


# =============================================================================
# BrotherQL Adapter Tests  (no DB)
# =============================================================================

class BrotherQLAdapterTests(DjangoSimpleTestCase):
    def test_print_images_calls_brother_ql(self):
        from PIL import Image
        from checkin.services.printers.brother_ql_adapter import BrotherQLAdapter

        img = Image.new("RGB", (696, 200), "white")
        adapter = BrotherQLAdapter("tcp://192.168.1.100", "QL-800")

        with patch("checkin.services.printers.brother_ql_adapter.BrotherQLRaster") as mock_raster_cls, \
             patch("checkin.services.printers.brother_ql_adapter.convert") as mock_convert, \
             patch("checkin.services.printers.brother_ql_adapter.ql_send") as mock_send:
            mock_raster = MagicMock()
            mock_raster.data = b"raster_data"
            mock_raster_cls.return_value = mock_raster
            result = adapter.print_images([img])

        self.assertTrue(result)
        mock_raster_cls.assert_called_once_with("QL-800")
        mock_convert.assert_called_once()
        mock_send.assert_called_once()

    def test_print_images_returns_false_when_brother_ql_not_installed(self):
        from checkin.services.printers.brother_ql_adapter import BrotherQLAdapter
        from PIL import Image

        img = Image.new("RGB", (696, 200), "white")
        adapter = BrotherQLAdapter("tcp://192.168.1.100", "QL-800")

        with patch("checkin.services.printers.brother_ql_adapter.BROTHER_QL_AVAILABLE", False):
            result = adapter.print_images([img])
        self.assertFalse(result)


# =============================================================================
# ESC/POS Adapter Tests  (no DB)
# =============================================================================

class ESCPOSAdapterTests(DjangoSimpleTestCase):
    def test_print_images_calls_escpos(self):
        from PIL import Image
        from checkin.services.printers.escpos_adapter import ESCPOSAdapter

        img = Image.new("RGB", (560, 200), "white")
        adapter = ESCPOSAdapter("tcp://192.168.1.101:9100")

        mock_printer = MagicMock()
        with patch("checkin.services.printers.escpos_adapter.NetworkPrinter", return_value=mock_printer):
            result = adapter.print_images([img])

        self.assertTrue(result)
        mock_printer.image.assert_called_once_with(img)
        mock_printer.cut.assert_called_once()
        mock_printer.close.assert_called_once()
