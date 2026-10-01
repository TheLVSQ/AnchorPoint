"""CSV export helpers that neutralize spreadsheet formula injection.

Names, emails and notes in exports can come from public forms (event
registration, kiosk quick-register). A cell such as =HYPERLINK(...) would run
as a formula when staff open the CSV in Excel or Google Sheets. Prefixing such
cells with an apostrophe makes the spreadsheet treat them as plain text.
"""
import csv

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


class SafeCsvWriter:
    """Drop-in for csv.writer(...) whose writerow() escapes formula cells."""

    def __init__(self, fileobj, **kwargs):
        self._writer = csv.writer(fileobj, **kwargs)

    def writerow(self, row):
        return self._writer.writerow([safe_cell(v) for v in row])
