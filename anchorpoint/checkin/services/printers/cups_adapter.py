"""
CUPS Printer Adapter

Universal printer support via CUPS (Common Unix Printing System).
Works with any printer that has a driver installed on the system.

This is the most compatible option - if it works from your OS, it works here.

Requires: pip install pycups (Linux/Mac only)
On Windows, falls back to using the default system print command.
"""

import logging
import platform
import subprocess
import tempfile

from .base import BasePrinterAdapter

logger = logging.getLogger(__name__)


class CUPSAdapter(BasePrinterAdapter):
    """
    Adapter for CUPS printing (works with any system printer).

    Connection string is simply the printer name as it appears in the system.
    Examples:
    - "Brother_QL-820NWB"
    - "HP_LaserJet"
    - "Thermal_Receipt_Printer"
    """

    def __init__(self, connection_string: str, **kwargs):
        super().__init__(connection_string, **kwargs)
        self.printer_name = connection_string
        self._cups_conn = None

    def _get_cups_connection(self):
        """Get CUPS connection (Linux/Mac only)."""
        if self._cups_conn is not None:
            return self._cups_conn

        if platform.system() == "Windows":
            return None

        try:
            import cups

            self._cups_conn = cups.Connection()
            return self._cups_conn
        except ImportError:
            logger.warning(
                "pycups not installed. Install with: pip install pycups"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to connect to CUPS: {e}")
            return None

    def print_image(self, image_bytes: bytes) -> bool:
        """
        Print a PNG image via system printer.

        Args:
            image_bytes: PNG image data

        Returns:
            True if print job was submitted successfully
        """
        # Save image to temporary file
        with tempfile.NamedTemporaryFile(
            suffix=".png", delete=False
        ) as tmp_file:
            tmp_file.write(image_bytes)
            tmp_path = tmp_file.name

        try:
            if platform.system() == "Windows":
                return self._print_windows(tmp_path)
            else:
                return self._print_cups(tmp_path)
        except Exception as e:
            logger.error(f"Print error: {e}")
            return False
        finally:
            # Clean up temp file
            import os

            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _print_cups(self, file_path: str) -> bool:
        """Print via CUPS on Linux/Mac."""
        conn = self._get_cups_connection()

        if conn:
            # Use pycups
            try:
                job_id = conn.printFile(
                    self.printer_name,
                    file_path,
                    "AnchorPoint Label",
                    {},
                )
                logger.info(f"CUPS print job {job_id} submitted")
                return True
            except Exception as e:
                logger.error(f"CUPS print error: {e}")
                return False
        else:
            # Fall back to lp command
            try:
                result = subprocess.run(
                    ["lp", "-d", self.printer_name, file_path],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    logger.info(f"Print job submitted via lp command")
                    return True
                else:
                    logger.error(f"lp command failed: {result.stderr}")
                    return False
            except FileNotFoundError:
                logger.error("lp command not found")
                return False

    def _print_windows(self, file_path: str) -> bool:
        """Print via Windows print command."""
        try:
            # Use Windows print command
            # This opens the default image viewer's print dialog
            # For silent printing, we'd need win32print
            import os

            os.startfile(file_path, "print")
            logger.info("Windows print dialog opened")
            return True
        except Exception as e:
            logger.error(f"Windows print error: {e}")

            # Try PowerShell as fallback
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-Command",
                        f'Start-Process -FilePath "{file_path}" -Verb Print',
                    ],
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0
            except Exception as e2:
                logger.error(f"PowerShell print error: {e2}")
                return False

    def is_available(self) -> bool:
        """Check if printer is available in the system."""
        if platform.system() == "Windows":
            # On Windows, we can't easily check without win32print
            return True  # Assume available

        conn = self._get_cups_connection()
        if conn:
            try:
                printers = conn.getPrinters()
                return self.printer_name in printers
            except Exception:
                return False

        # Try lpstat command
        try:
            result = subprocess.run(
                ["lpstat", "-p", self.printer_name],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def list_printers(self) -> list:
        """List available system printers."""
        if platform.system() == "Windows":
            # Would need win32print for proper listing
            return []

        conn = self._get_cups_connection()
        if conn:
            try:
                return list(conn.getPrinters().keys())
            except Exception:
                pass

        # Try lpstat command
        try:
            result = subprocess.run(
                ["lpstat", "-a"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                printers = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        printers.append(line.split()[0])
                return printers
        except FileNotFoundError:
            pass

        return []
