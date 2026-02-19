"""
Print Service

Orchestrates label generation and printing.
"""

import logging

from ..models import PrinterConfiguration, CheckIn
from .label_generator import LabelGenerator
from .printers import ESCPOSAdapter, CUPSAdapter

logger = logging.getLogger(__name__)


def get_printer_adapter(config: PrinterConfiguration):
    """
    Get the appropriate printer adapter for a configuration.

    Args:
        config: PrinterConfiguration model instance

    Returns:
        Printer adapter instance
    """
    adapters = {
        "escpos": ESCPOSAdapter,
        "cups": CUPSAdapter,
        # Future: "brother": BrotherQLAdapter,
        # Future: "zpl": ZPLAdapter,
    }

    adapter_class = adapters.get(config.printer_type)
    if not adapter_class:
        raise ValueError(f"Unknown printer type: {config.printer_type}")

    return adapter_class(
        config.connection_string,
        dpi=config.dpi,
        width_mm=config.label_width_mm,
        height_mm=config.label_height_mm,
    )


class PrintService:
    """Service for printing check-in labels."""

    def __init__(self, printer_config: PrinterConfiguration = None):
        """
        Initialize print service.

        Args:
            printer_config: PrinterConfiguration to use.
                           If None, uses the default printer.
        """
        if printer_config is None:
            printer_config = PrinterConfiguration.objects.filter(
                is_active=True, is_default=True
            ).first()

            if printer_config is None:
                printer_config = PrinterConfiguration.objects.filter(
                    is_active=True
                ).first()

        self.printer_config = printer_config
        self._adapter = None
        self._generator = None

    @property
    def adapter(self):
        """Get the printer adapter (lazy loaded)."""
        if self._adapter is None and self.printer_config:
            self._adapter = get_printer_adapter(self.printer_config)
        return self._adapter

    @property
    def generator(self):
        """Get the label generator (lazy loaded)."""
        if self._generator is None:
            if self.printer_config:
                self._generator = LabelGenerator(
                    width_mm=self.printer_config.label_width_mm,
                    height_mm=self.printer_config.label_height_mm,
                    dpi=self.printer_config.dpi,
                )
            else:
                # Use defaults
                self._generator = LabelGenerator()
        return self._generator

    def print_child_label(self, checkin: CheckIn) -> bool:
        """
        Print a child name tag label.

        Args:
            checkin: CheckIn instance

        Returns:
            True if successful
        """
        if not self.adapter:
            logger.error("No printer configured")
            return False

        try:
            label_bytes = self.generator.generate_child_label(checkin)
            success = self.adapter.print_image(label_bytes)

            if success:
                checkin.child_label_printed = True
                checkin.save(update_fields=["child_label_printed"])

            return success
        except Exception as e:
            logger.error(f"Failed to print child label: {e}")
            return False

    def print_parent_label(self, checkin: CheckIn, children_names: list = None) -> bool:
        """
        Print a parent claim tag label.

        Args:
            checkin: CheckIn instance (any child from the family)
            children_names: List of children's names

        Returns:
            True if successful
        """
        if not self.adapter:
            logger.error("No printer configured")
            return False

        try:
            label_bytes = self.generator.generate_parent_label(checkin, children_names)
            success = self.adapter.print_image(label_bytes)

            if success:
                checkin.parent_label_printed = True
                checkin.save(update_fields=["parent_label_printed"])

            return success
        except Exception as e:
            logger.error(f"Failed to print parent label: {e}")
            return False

    def print_allergy_label(self, checkin: CheckIn) -> bool:
        """
        Print an allergy alert label.

        Args:
            checkin: CheckIn instance

        Returns:
            True if successful
        """
        if not self.adapter:
            logger.error("No printer configured")
            return False

        try:
            label_bytes = self.generator.generate_allergy_label(checkin)
            return self.adapter.print_image(label_bytes)
        except Exception as e:
            logger.error(f"Failed to print allergy label: {e}")
            return False

    def print_checkin_labels(self, checkins: list) -> dict:
        """
        Print all labels for a check-in (child tags + parent tag + allergy alerts).

        Args:
            checkins: List of CheckIn instances (usually siblings)

        Returns:
            Dict with results: {"child": [bool], "parent": bool, "allergy": [bool]}
        """
        results = {
            "child": [],
            "parent": False,
            "allergy": [],
        }

        if not checkins:
            return results

        children_names = []
        for checkin in checkins:
            person = checkin.person
            name = f"{person.first_name} {person.last_name[0]}." if person.last_name else person.first_name
            children_names.append(name)

            # Print child label
            results["child"].append(self.print_child_label(checkin))

            # Print allergy label if needed
            if person.allergies:
                results["allergy"].append(self.print_allergy_label(checkin))

        # Print one parent label for all children
        results["parent"] = self.print_parent_label(checkins[0], children_names)

        return results

    def test_printer(self) -> bool:
        """
        Print a test label.

        Returns:
            True if test print was successful
        """
        if not self.adapter:
            logger.error("No printer configured")
            return False

        return self.adapter.test_print()

    def is_printer_available(self) -> bool:
        """
        Check if the configured printer is available.

        Returns:
            True if printer is available
        """
        if not self.adapter:
            return False

        return self.adapter.is_available()
