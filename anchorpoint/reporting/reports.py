"""Report registry.

A report declares its columns and a row query; the generic views render it as
an on-screen table or a CSV download. Add a report by subclassing Report and
registering it — no new views or URLs needed.
"""

from django import forms

from checkin.models import CheckInSession
from groups.models import Group
from households.models import HouseholdMember


# --------------------------------------------------------------------------- #
# Framework
# --------------------------------------------------------------------------- #

class Report:
    slug = ""
    name = ""
    description = ""
    param_form_class = None  # optional forms.Form subclass

    def columns(self):
        """Return [(key, header), ...]."""
        raise NotImplementedError

    def get_rows(self, params):
        """Return an iterable of dicts keyed by the column keys. params is the
        cleaned_data of param_form_class (or {} when there's no form)."""
        raise NotImplementedError


REGISTRY = {}


def register(report_cls):
    REGISTRY[report_cls.slug] = report_cls
    return report_cls


def get_report(slug):
    cls = REGISTRY.get(slug)
    return cls() if cls else None


def all_reports():
    return [cls() for cls in REGISTRY.values()]


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

def _guardian(person):
    """Best guardian for a person: the household's primary adult, else the
    first adult member. Returns a Person or None."""
    household = person.households.all().first()
    if household is None:
        return None
    if household.primary_adult_id:
        return household.primary_adult
    membership = (
        household.memberships.filter(
            relationship_type=HouseholdMember.RelationshipType.ADULT
        )
        .select_related("person")
        .first()
    )
    return membership.person if membership else None


def _yes_no(value):
    return "Yes" if value else "No"


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

class _GroupParamForm(forms.Form):
    group = forms.ModelChoiceField(
        queryset=Group.objects.order_by("name"), label="Group"
    )


@register
class GroupRosterReport(Report):
    slug = "group-roster"
    name = "Group Roster"
    description = (
        "Everyone enrolled in a group (e.g. VBS) with guardian contact, "
        "allergies, security/custody concerns, and photo permission."
    )
    param_form_class = _GroupParamForm

    def columns(self):
        return [
            ("first_name", "First Name"),
            ("last_name", "Last Name"),
            ("age", "Age"),
            ("grade", "Grade"),
            ("guardian", "Guardian"),
            ("guardian_phone", "Guardian Phone"),
            ("guardian_email", "Guardian Email"),
            ("allergies", "Allergies"),
            ("custody", "Security/Custody"),
            ("unauthorized_pickup", "Unauthorized Pickup"),
            ("photo_consent", "Photo OK"),
        ]

    def get_rows(self, params):
        group = params["group"]
        people = (
            group.memberships.select_related("person")
            .prefetch_related("person__households__memberships__person")
            .order_by("person__last_name", "person__first_name")
        )
        for membership in people:
            p = membership.person
            g = _guardian(p)
            custody = ""
            if p.custody_flag:
                custody = (p.custody_notes or "Flagged").strip()
            yield {
                "first_name": p.first_name,
                "last_name": p.last_name,
                "age": p.age if p.age is not None else "",
                "grade": p.get_grade_display() if p.grade else "",
                "guardian": str(g) if g else "",
                "guardian_phone": (g.phone if g else "") or "",
                "guardian_email": (g.email if g else "") or "",
                "allergies": (p.allergies or "").strip(),
                "custody": custody,
                "unauthorized_pickup": (p.unauthorized_pickup or "").strip(),
                "photo_consent": _yes_no(p.photo_consent),
            }


class _SessionParamForm(forms.Form):
    session = forms.ModelChoiceField(
        queryset=CheckInSession.objects.order_by("-date", "name"),
        label="Check-in session",
    )


@register
class SessionAttendanceReport(Report):
    slug = "session-attendance"
    name = "Session Attendance"
    description = (
        "Everyone tied to a check-in session — expected, present, or checked "
        "out — with room, times, allergies, custody, and photo permission."
    )
    param_form_class = _SessionParamForm

    def columns(self):
        return [
            ("first_name", "First Name"),
            ("last_name", "Last Name"),
            ("status", "Status"),
            ("room", "Room"),
            ("arrived_at", "Arrived"),
            ("checked_out_at", "Checked Out"),
            ("security_code", "Code"),
            ("allergies", "Allergies"),
            ("custody", "Security/Custody"),
            ("guardian_phone", "Guardian Phone"),
            ("photo_consent", "Photo OK"),
        ]

    def get_rows(self, params):
        session = params["session"]
        checkins = (
            session.checkins.select_related("person", "room")
            .prefetch_related("person__households__memberships__person")
            .order_by("person__last_name", "person__first_name")
        )
        for c in checkins:
            p = c.person
            g = _guardian(p)
            if c.checked_out_at:
                status = "Checked out"
            elif c.arrived_at:
                status = "Present"
            elif c.no_show:
                status = "No-show"
            else:
                status = "Expected"
            yield {
                "first_name": p.first_name,
                "last_name": p.last_name,
                "status": status,
                "room": c.room.name if c.room else "",
                "arrived_at": c.arrived_at.strftime("%-I:%M %p") if c.arrived_at else "",
                "checked_out_at": c.checked_out_at.strftime("%-I:%M %p") if c.checked_out_at else "",
                "security_code": c.security_code,
                "allergies": (p.allergies or "").strip(),
                "custody": (p.custody_notes or "Flagged").strip() if p.custody_flag else "",
                "guardian_phone": (g.phone if g else "") or "",
                "photo_consent": _yes_no(p.photo_consent),
            }
