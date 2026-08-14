"""Report registry.

A report declares its columns and a row query; the generic views render it as
an on-screen table or a CSV download. Add a report by subclassing Report and
registering it — no new views or URLs needed.
"""

import calendar

from django import forms
from django.utils import timezone

from checkin.models import CheckInSession
from groups.models import Group
from households.models import HouseholdMember
from people.models import Person


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
    """Best guardian for a person: the (deterministic) primary household's
    primary adult, else its first adult member. Returns a Person or None."""
    household = person.primary_household
    if household is None:
        return None
    if household.primary_adult_id:
        return household.primary_adult
    membership = (
        household.memberships.filter(
            relationship_type=HouseholdMember.RelationshipType.ADULT
        )
        .select_related("person")
        .order_by("person__id")
        .first()
    )
    return membership.person if membership else None


def _yes_no(value):
    return "Yes" if value else "No"


_ADDRESS_COLUMNS = [
    ("address_line1", "Address Line 1"),
    ("address_line2", "Address Line 2"),
    ("city", "City"),
    ("state", "State"),
    ("postal_code", "ZIP"),
]


def _mailing_address(person):
    """Mailing address for a person: their own if set, else their primary
    household's (kids usually carry no address of their own). Returns a dict
    keyed like _ADDRESS_COLUMNS; all-empty when neither has one."""
    for source in (person, person.primary_household):
        if source is not None and (source.address_line1 or source.city):
            return {
                "address_line1": source.address_line1 or "",
                "address_line2": source.address_line2 or "",
                "city": source.city or "",
                "state": source.state or "",
                "postal_code": source.postal_code or "",
            }
    return {key: "" for key, _header in _ADDRESS_COLUMNS}


def _is_child(person):
    """Child = under 18 by birthdate; with no birthdate, fall back to whether
    any household lists them as a CHILD member."""
    if person.is_minor is not None:
        return person.is_minor
    return any(
        m.relationship_type == HouseholdMember.RelationshipType.CHILD
        for h in person.households.all()
        for m in h.memberships.all()
        if m.person_id == person.id
    )


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
            ("photo_consent", "Photo Consent"),
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
                "photo_consent": p.get_photo_consent_display(),
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
            ("age", "Age"),
            ("grade", "Grade"),
            ("status", "Status"),
            ("room", "Room"),
            ("arrived_at", "Arrived"),
            ("checked_out_at", "Checked Out"),
            ("security_code", "Code"),
            ("allergies", "Allergies"),
            ("custody", "Security/Custody"),
            ("guardian_phone", "Guardian Phone"),
            ("photo_consent", "Photo Consent"),
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
                "age": p.age if p.age is not None else "",
                "grade": p.get_grade_display() if p.grade else "",
                "status": status,
                "room": c.room.name if c.room else "",
                "arrived_at": c.arrived_at.strftime("%-I:%M %p") if c.arrived_at else "",
                "checked_out_at": c.checked_out_at.strftime("%-I:%M %p") if c.checked_out_at else "",
                "security_code": c.security_code,
                "allergies": (p.allergies or "").strip(),
                "custody": (p.custody_notes or "Flagged").strip() if p.custody_flag else "",
                "guardian_phone": (g.phone if g else "") or "",
                "photo_consent": p.get_photo_consent_display(),
            }


class _MonthParamForm(forms.Form):
    month = forms.TypedChoiceField(
        choices=[(i, calendar.month_name[i]) for i in range(1, 13)],
        coerce=int,
        label="Birthday month",
    )


@register
class BirthdayPostcardReport(Report):
    slug = "birthday-postcards"
    name = "Birthday Postcards (Kids)"
    description = (
        "Kids (under 18) with a birthday in the chosen month, with mailing "
        "address (theirs, or their household's) and guardian — ready for a "
        "postcard mail merge."
    )
    param_form_class = _MonthParamForm

    def columns(self):
        return [
            ("first_name", "First Name"),
            ("last_name", "Last Name"),
            ("birthday", "Birthday"),
            ("day", "Day"),
            ("turning", "Turning"),
            ("guardian", "Guardian"),
            ("household", "Household"),
        ] + _ADDRESS_COLUMNS

    def get_rows(self, params):
        month = params["month"]
        today = timezone.localdate()
        people = (
            Person.objects.filter(birthdate__month=month)
            .exclude(status="inactive")
            .prefetch_related("households__memberships__person")
            .order_by("birthdate__day", "last_name", "first_name")
        )
        for p in people:
            if not _is_child(p):
                continue
            g = _guardian(p)
            household = p.primary_household
            # Age they turn on their next birthday — compared by (month, day)
            # rather than building a date, so Feb 29 birthdays can't crash.
            next_year = today.year
            if (p.birthdate.month, p.birthdate.day) < (today.month, today.day):
                next_year += 1
            yield {
                "first_name": p.first_name,
                "last_name": p.last_name,
                "birthday": p.birthdate.strftime("%B %-d"),
                "day": p.birthdate.day,
                "turning": next_year - p.birthdate.year,
                "guardian": str(g) if g else "",
                "household": household.name if household else "",
                **_mailing_address(p),
            }


@register
class GroupMailingListReport(Report):
    slug = "group-mailing-list"
    name = "Group Mailing List"
    description = (
        "Everyone enrolled in a group (e.g. VBS 2026 Participants) with "
        "birthdate, guardian, and mailing address (theirs, or their "
        "household's) — ready for a postcard mail merge."
    )
    param_form_class = _GroupParamForm

    def columns(self):
        return [
            ("first_name", "First Name"),
            ("last_name", "Last Name"),
            ("age", "Age"),
            ("birthdate", "Birthdate"),
            ("guardian", "Guardian"),
            ("household", "Household"),
        ] + _ADDRESS_COLUMNS

    def get_rows(self, params):
        group = params["group"]
        memberships = (
            group.memberships.select_related("person")
            .prefetch_related("person__households__memberships__person")
            .order_by("person__last_name", "person__first_name")
        )
        for membership in memberships:
            p = membership.person
            g = _guardian(p)
            household = p.primary_household
            yield {
                "first_name": p.first_name,
                "last_name": p.last_name,
                "age": p.age if p.age is not None else "",
                "birthdate": p.birthdate.isoformat() if p.birthdate else "",
                "guardian": str(g) if g else "",
                "household": household.name if household else "",
                **_mailing_address(p),
            }


@register
class MissingDataReport(Report):
    slug = "missing-data"
    name = "Missing Data"
    description = (
        "People whose records are missing key data — mailing address or "
        "birthdate for everyone, email/phone for adults, grade/guardian/"
        "emergency contact/photo consent for kids. Inactive people are "
        "excluded."
    )

    def columns(self):
        return [
            ("first_name", "First Name"),
            ("last_name", "Last Name"),
            ("kind", "Adult/Child"),
            ("status", "Status"),
            ("missing_count", "# Missing"),
            ("missing", "Missing"),
        ]

    def get_rows(self, params):
        people = (
            Person.objects.exclude(status="inactive")
            .prefetch_related("households__memberships__person")
            .order_by("last_name", "first_name")
        )
        for p in people:
            child = _is_child(p)
            g = _guardian(p)
            missing = []
            address = _mailing_address(p)
            if not (address["address_line1"] or address["city"]):
                missing.append("address")
            if not p.birthdate:
                missing.append("birthdate")
            if child:
                if not p.grade:
                    missing.append("grade")
                if g is None:
                    missing.append("guardian")
                if not (p.emergency_contact_phone or (g.phone if g else "")):
                    missing.append("emergency contact phone")
                if p.photo_consent == "unknown":
                    missing.append("photo consent")
            else:
                if not p.email:
                    missing.append("email")
                if not p.phone:
                    missing.append("phone")
            if not missing:
                continue
            yield {
                "first_name": p.first_name,
                "last_name": p.last_name,
                "kind": "Child" if child else "Adult",
                "status": p.get_status_display(),
                "missing_count": len(missing),
                "missing": ", ".join(missing),
            }
