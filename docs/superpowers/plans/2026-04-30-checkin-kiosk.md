# Check-In Kiosk System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the `attendance/` and `checkin/` apps into a single check-in module with a tablet kiosk flow, eligibility-based family check-in, and CSS-based thermal label printing.

**Architecture:** Migrate `CheckInConfiguration` and `CheckInWindow` from `attendance/` into `checkin/`, add eligibility filters (age/grade/group) to configuration, simplify Room to a physical space, add custody fields to Person, rebuild kiosk views with the new flow (PIN → lookup → select → rooms → print), and replace Pillow label generation with CSS `@media print`.

**Tech Stack:** Django 5.2, HTMX, PostgreSQL, CSS `@media print`, Google Fonts (Outfit)

**Design Spec:** `docs/superpowers/specs/2026-04-30-checkin-kiosk-design.md`

---

## File Structure

### New Files
- `anchorpoint/checkin/services/eligibility.py` — eligibility check logic
- `anchorpoint/checkin/services/quick_registration.py` — new family registration service
- `anchorpoint/checkin/services/session_manager.py` — auto-create sessions from config+window
- `anchorpoint/checkin/templates/checkin/kiosk/unlock.html` — PIN entry screen
- `anchorpoint/checkin/templates/checkin/kiosk/lookup_new.html` — family lookup (replaces lookup.html)
- `anchorpoint/checkin/templates/checkin/kiosk/family_select.html` — member selection + room pick
- `anchorpoint/checkin/templates/checkin/kiosk/confirmation.html` — success + print trigger
- `anchorpoint/checkin/templates/checkin/kiosk/quick_register.html` — new family form
- `anchorpoint/checkin/templates/checkin/kiosk/no_sessions.html` — "not currently open" message
- `anchorpoint/checkin/templates/checkin/labels/child_label.html` — print label partial
- `anchorpoint/checkin/templates/checkin/labels/pickup_label.html` — print label partial
- `anchorpoint/checkin/templates/checkin/config_list.html` — admin config management
- `anchorpoint/checkin/templates/checkin/config_form.html` — admin config create/edit
- `anchorpoint/checkin/tests/test_models.py` — model tests
- `anchorpoint/checkin/tests/test_eligibility.py` — eligibility service tests
- `anchorpoint/checkin/tests/test_kiosk_views.py` — kiosk flow tests
- `anchorpoint/checkin/tests/test_quick_registration.py` — quick registration tests
- `anchorpoint/checkin/tests/test_session_manager.py` — session manager tests
- `anchorpoint/checkin/tests/__init__.py` — package init

### Modified Files
- `anchorpoint/checkin/models.py` — migrate CheckInConfiguration + CheckInWindow, simplify Room, modify CheckInSession
- `anchorpoint/checkin/views.py` — rewrite kiosk views, add config admin views
- `anchorpoint/checkin/urls.py` — update URL patterns
- `anchorpoint/checkin/forms.py` — add config forms, quick registration form, update kiosk forms
- `anchorpoint/people/models.py` — add custody fields
- `anchorpoint/core/permissions.py` — add `@checkin_admin_required` decorator
- `anchorpoint/anchorpoint/urls.py` — remove attendance include
- `anchorpoint/anchorpoint/settings.py` — remove attendance from INSTALLED_APPS

### Deleted Files/Directories
- `anchorpoint/attendance/` — entire app (models, views, urls, forms, templates, migrations, admin, tests)

---

## Task 1: Add `@checkin_admin_required` Permission Decorator

**Files:**
- Modify: `anchorpoint/core/permissions.py`
- Modify: `anchorpoint/core/tests.py`

- [ ] **Step 1: Write the failing test**

Create a test for the new permission level in `anchorpoint/core/tests.py`. Add at the end of the file:

```python
class CheckinAdminRequiredTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="pw")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()

        self.staff = User.objects.create_user(username="staff", password="pw")
        self.staff.profile.role = UserProfile.Role.STAFF
        self.staff.profile.save()

        self.vol_admin = User.objects.create_user(username="voladmin", password="pw")
        self.vol_admin.profile.role = UserProfile.Role.VOLUNTEER_ADMIN
        self.vol_admin.profile.save()

        self.volunteer = User.objects.create_user(username="vol", password="pw")
        self.volunteer.profile.role = UserProfile.Role.VOLUNTEER
        self.volunteer.profile.save()

    def test_admin_allowed(self):
        from core.permissions import is_checkin_admin
        self.assertTrue(is_checkin_admin(self.admin))

    def test_staff_allowed(self):
        from core.permissions import is_checkin_admin
        self.assertTrue(is_checkin_admin(self.staff))

    def test_volunteer_admin_allowed(self):
        from core.permissions import is_checkin_admin
        self.assertTrue(is_checkin_admin(self.vol_admin))

    def test_volunteer_denied(self):
        from core.permissions import is_checkin_admin
        self.assertFalse(is_checkin_admin(self.volunteer))

    def test_unauthenticated_denied(self):
        from django.contrib.auth.models import AnonymousUser
        from core.permissions import is_checkin_admin
        self.assertFalse(is_checkin_admin(AnonymousUser()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test core.tests.CheckinAdminRequiredTests -v2`
Expected: ImportError — `is_checkin_admin` not found

- [ ] **Step 3: Implement the permission check and decorator**

Add to `anchorpoint/core/permissions.py` after the `is_staff_or_above` function (after line 40):

```python
def is_checkin_admin(user):
    """Check if user can manage check-in configurations (admin, staff, or volunteer admin)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = _get_user_profile(user)
    if not profile:
        return False
    return profile.role in ("admin", "staff", "volunteer_admin")
```

Add the decorator after `communications_required` (after line 116):

```python
def checkin_admin_required(view_func):
    """
    Decorator that requires check-in admin access (admin, staff, or volunteer admin).

    Usage:
        @checkin_admin_required
        def manage_checkin_config(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.shortcuts import redirect
            return redirect("login")
        if not is_checkin_admin(request.user):
            return HttpResponseForbidden(
                "You do not have permission to manage check-in settings."
            )
        return view_func(request, *args, **kwargs)
    return wrapper
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test core.tests.CheckinAdminRequiredTests -v2`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add anchorpoint/core/permissions.py anchorpoint/core/tests.py
git commit -m "feat: add @checkin_admin_required permission decorator

Allows admin, staff, and volunteer admin roles to manage check-in
configurations. Regular volunteers are excluded."
```

---

## Task 2: Add Custody Fields to Person Model

**Files:**
- Modify: `anchorpoint/people/models.py`
- Create: `anchorpoint/people/tests_custody.py`

- [ ] **Step 1: Write the failing test**

Create `anchorpoint/people/tests_custody.py`:

```python
from datetime import date, timedelta

from django.test import TestCase

from people.models import Person


class PersonCustodyFieldTests(TestCase):
    def test_custody_flag_defaults_false(self):
        person = Person.objects.create(first_name="Test", last_name="Child")
        self.assertFalse(person.custody_flag)

    def test_custody_fields_save_and_retrieve(self):
        person = Person.objects.create(
            first_name="Test",
            last_name="Child",
            birthdate=date.today() - timedelta(days=365 * 7),
            custody_flag=True,
            custody_notes="Parents divorced, mother has primary custody.",
            unauthorized_pickup="John Doe - biological father",
        )
        person.refresh_from_db()
        self.assertTrue(person.custody_flag)
        self.assertIn("primary custody", person.custody_notes)
        self.assertIn("John Doe", person.unauthorized_pickup)

    def test_custody_fields_blank_by_default(self):
        person = Person.objects.create(first_name="Test", last_name="Child")
        self.assertEqual(person.custody_notes, "")
        self.assertEqual(person.unauthorized_pickup, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test people.tests_custody -v2`
Expected: Error — `custody_flag` field does not exist

- [ ] **Step 3: Add custody fields to Person model**

Add to `anchorpoint/people/models.py` in the Person model, after the `security_notes` field (around line 91):

```python
    # Custody/security tracking (only relevant for minors)
    custody_flag = models.BooleanField(default=False)
    custody_notes = models.TextField(blank=True)
    unauthorized_pickup = models.TextField(blank=True)
```

- [ ] **Step 4: Create and run migration**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py makemigrations people -n add_custody_fields`
Then: `cd anchorpoint && ../venv/Scripts/python.exe manage.py migrate`

- [ ] **Step 5: Run test to verify it passes**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test people.tests_custody -v2`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/people/
git commit -m "feat: add custody tracking fields to Person model

Adds custody_flag, custody_notes, and unauthorized_pickup fields.
Only relevant for minors — UI will conditionally show these."
```

---

## Task 3: Migrate Models into checkin/ and Simplify Room

**Files:**
- Modify: `anchorpoint/checkin/models.py`

- [ ] **Step 1: Remove age/grade fields from Room**

In `anchorpoint/checkin/models.py`, remove these lines from the Room model (lines 27-31):

```python
    # Age/grade range for auto-assignment
    min_age = models.PositiveIntegerField(null=True, blank=True)
    max_age = models.PositiveIntegerField(null=True, blank=True)
    min_grade = models.CharField(max_length=20, blank=True)
    max_grade = models.CharField(max_length=20, blank=True)
```

- [ ] **Step 2: Add CheckInConfiguration model**

Add to `anchorpoint/checkin/models.py` after the imports, before the Room model. Add needed imports first:

```python
from django.core.exceptions import ValidationError
```

Then add the model:

```python
class CheckInConfiguration(models.Model):
    """Named check-in configuration controlling schedule, eligibility, and rooms."""

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    welcome_message = models.CharField(max_length=255, blank=True)
    location_name = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    rooms = models.ManyToManyField("Room", related_name="configurations", blank=True)

    # Eligibility filters — all optional, OR logic
    min_age = models.PositiveIntegerField(null=True, blank=True)
    max_age = models.PositiveIntegerField(null=True, blank=True)
    min_grade = models.CharField(
        max_length=20, choices=Person.GRADE_CHOICES, blank=True
    )
    max_grade = models.CharField(
        max_length=20, choices=Person.GRADE_CHOICES, blank=True
    )
    groups = models.ManyToManyField(
        "groups.Group", related_name="checkin_configurations", blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def active_windows(self):
        return self.windows.filter(is_active=True)

    def open_windows(self, reference_time=None):
        now = reference_time or timezone.localtime()
        return [w for w in self.active_windows() if w.is_checkin_open(now)]

    def is_open(self, reference_time=None):
        return bool(self.open_windows(reference_time))

    def schedule_summary(self):
        windows = list(self.active_windows())
        if not windows:
            return "No schedule"
        parts = []
        for w in windows:
            opens = w.checkin_opens.strftime("%I:%M %p").lstrip("0")
            closes = w.checkin_closes.strftime("%I:%M %p").lstrip("0")
            if w.schedule_type == CheckInWindow.TYPE_SPECIFIC_DATE and w.specific_date:
                parts.append(f"{w.specific_date:%b %d, %Y} {opens}-{closes}")
            else:
                day = w.get_day_of_week_display() if w.day_of_week is not None else "Day"
                parts.append(f"{day} {opens}-{closes}")
        return ", ".join(parts)

    def has_filters(self):
        return any([
            self.min_age is not None,
            self.max_age is not None,
            self.min_grade,
            self.max_grade,
            self.groups.exists(),
        ])
```

- [ ] **Step 3: Add CheckInWindow model**

Add after CheckInConfiguration:

```python
class CheckInWindow(models.Model):
    """Schedule window with four-time model for check-in availability."""

    TYPE_WEEKLY = "weekly"
    TYPE_SPECIFIC_DATE = "specific_date"
    TYPE_CHOICES = [
        (TYPE_WEEKLY, "Recurring (weekly)"),
        (TYPE_SPECIFIC_DATE, "Specific date"),
    ]

    DAY_CHOICES = [
        (0, "Sunday"),
        (1, "Monday"),
        (2, "Tuesday"),
        (3, "Wednesday"),
        (4, "Thursday"),
        (5, "Friday"),
        (6, "Saturday"),
    ]

    configuration = models.ForeignKey(
        CheckInConfiguration, related_name="windows", on_delete=models.CASCADE
    )
    schedule_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_WEEKLY
    )
    day_of_week = models.IntegerField(choices=DAY_CHOICES, blank=True, null=True)
    specific_date = models.DateField(blank=True, null=True)

    checkin_opens = models.TimeField()
    event_starts = models.TimeField()
    checkin_closes = models.TimeField()
    event_ends = models.TimeField()

    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["schedule_type", "specific_date", "day_of_week", "checkin_opens"]

    def __str__(self):
        if self.schedule_type == self.TYPE_SPECIFIC_DATE and self.specific_date:
            return f"{self.configuration.name} on {self.specific_date:%Y-%m-%d}"
        day = dict(self.DAY_CHOICES).get(self.day_of_week, "Day")
        return f"{self.configuration.name} on {day} ({self.checkin_opens}-{self.checkin_closes})"

    def clean(self):
        if self.schedule_type == self.TYPE_SPECIFIC_DATE:
            if not self.specific_date:
                raise ValidationError("Specific date is required for date-based windows.")
        else:
            if self.day_of_week is None:
                raise ValidationError("Day of week is required for weekly windows.")
        if self.checkin_opens and self.checkin_closes and self.checkin_opens >= self.checkin_closes:
            raise ValidationError("Check-in close time must be after check-in open time.")
        if self.event_starts and self.event_ends and self.event_starts >= self.event_ends:
            raise ValidationError("Event end time must be after event start time.")

    def is_checkin_open(self, reference_time=None):
        now = reference_time or timezone.localtime()
        current_time = now.time()
        if self.schedule_type == self.TYPE_SPECIFIC_DATE:
            if not self.specific_date or self.specific_date != now.date():
                return False
        else:
            if self.day_of_week is None or self.day_of_week != now.weekday():
                return False
        return self.checkin_opens <= current_time <= self.checkin_closes

    @property
    def display_label(self):
        opens = self.checkin_opens.strftime("%I:%M %p").lstrip("0")
        closes = self.checkin_closes.strftime("%I:%M %p").lstrip("0")
        if self.schedule_type == self.TYPE_SPECIFIC_DATE and self.specific_date:
            return f"{self.configuration.name} • {self.specific_date:%b %d} {opens}-{closes}"
        day = self.get_day_of_week_display() if self.day_of_week is not None else "Day"
        return f"{self.configuration.name} • {day} {opens}-{closes}"
```

- [ ] **Step 4: Modify CheckInSession to link to configuration and window**

Replace the existing CheckInSession model with:

```python
class CheckInSession(models.Model):
    """Concrete instance of a configuration + window for a specific date."""

    configuration = models.ForeignKey(
        CheckInConfiguration,
        on_delete=models.CASCADE,
        related_name="sessions",
        null=True,
        blank=True,
    )
    window = models.ForeignKey(
        CheckInWindow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions",
    )

    name = models.CharField(max_length=100)
    date = models.DateField()

    checkin_opens = models.TimeField()
    checkin_closes = models.TimeField()
    event_starts = models.TimeField()
    event_ends = models.TimeField()

    event = models.ForeignKey(
        "events.Event", on_delete=models.SET_NULL, null=True, blank=True
    )

    rooms = models.ManyToManyField(Room, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_sessions",
    )

    class Meta:
        ordering = ["-date", "-checkin_opens"]

    def __str__(self):
        return f"{self.name} - {self.date}"

    @property
    def is_open(self):
        if not self.is_active:
            return False
        now = timezone.localtime()
        if self.date != now.date():
            return False
        return self.checkin_opens <= now.time() <= self.checkin_closes

    def total_checked_in(self):
        return self.checkins.filter(checked_out_at__isnull=True).count()
```

- [ ] **Step 5: Create migration**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py makemigrations checkin -n migrate_config_simplify_room`
Then: `cd anchorpoint && ../venv/Scripts/python.exe manage.py migrate`

Note: The migration will need manual adjustment — the `start_time`/`end_time` fields on CheckInSession need to be renamed to `checkin_opens`/`checkin_closes`, and `event_starts`/`event_ends` need to be added. Django may generate a remove+add instead of rename. Review the migration and use `RenameField` operations if needed:

```python
migrations.RenameField(model_name='checkinsession', old_name='start_time', new_name='checkin_opens'),
migrations.RenameField(model_name='checkinsession', old_name='end_time', new_name='checkin_closes'),
migrations.AddField(model_name='checkinsession', name='event_starts', field=models.TimeField(default='00:00:00')),
migrations.AddField(model_name='checkinsession', name='event_ends', field=models.TimeField(default='00:00:00')),
```

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/checkin/
git commit -m "feat: migrate CheckInConfiguration and CheckInWindow into checkin module

Adds CheckInConfiguration with eligibility filters (age/grade/group,
OR logic) and CheckInWindow with four-time model (checkin_opens,
event_starts, checkin_closes, event_ends). Simplifies Room to a
physical space only. Adds configuration/window FKs to CheckInSession."
```

---

## Task 4: Create Eligibility Service

**Files:**
- Create: `anchorpoint/checkin/services/eligibility.py`
- Create: `anchorpoint/checkin/tests/__init__.py`
- Create: `anchorpoint/checkin/tests/test_eligibility.py`

- [ ] **Step 1: Create tests package**

Create `anchorpoint/checkin/tests/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `anchorpoint/checkin/tests/test_eligibility.py`:

```python
from datetime import date, timedelta

from django.test import TestCase

from checkin.models import CheckInConfiguration
from checkin.services.eligibility import is_person_eligible
from groups.models import Group, GroupMembership
from people.models import Person


class EligibilityTests(TestCase):
    def setUp(self):
        self.config = CheckInConfiguration.objects.create(name="Test Config")

    def test_no_filters_everyone_eligible(self):
        person = Person.objects.create(first_name="John", last_name="Doe")
        self.assertTrue(is_person_eligible(person, self.config))

    def test_age_filter_match(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.save()
        child = Person.objects.create(
            first_name="Emma", last_name="Smith",
            birthdate=date.today() - timedelta(days=365 * 7),
        )
        self.assertTrue(is_person_eligible(child, self.config))

    def test_age_filter_no_match(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.save()
        adult = Person.objects.create(
            first_name="Mark", last_name="Smith",
            birthdate=date.today() - timedelta(days=365 * 35),
        )
        self.assertFalse(is_person_eligible(adult, self.config))

    def test_grade_filter_match(self):
        self.config.min_grade = "k"
        self.config.max_grade = "5"
        self.config.save()
        child = Person.objects.create(
            first_name="Liam", last_name="Smith", grade="3",
        )
        self.assertTrue(is_person_eligible(child, self.config))

    def test_grade_filter_no_match(self):
        self.config.min_grade = "k"
        self.config.max_grade = "5"
        self.config.save()
        teen = Person.objects.create(
            first_name="Tyler", last_name="Smith", grade="9",
        )
        self.assertFalse(is_person_eligible(teen, self.config))

    def test_group_filter_match(self):
        group = Group.objects.create(name="Volunteers", category="volunteer")
        self.config.groups.add(group)
        person = Person.objects.create(first_name="Sarah", last_name="Jones")
        GroupMembership.objects.create(group=group, person=person)
        self.assertTrue(is_person_eligible(person, self.config))

    def test_group_filter_no_match(self):
        group = Group.objects.create(name="Volunteers", category="volunteer")
        self.config.groups.add(group)
        person = Person.objects.create(first_name="Bob", last_name="Jones")
        self.assertFalse(is_person_eligible(person, self.config))

    def test_or_logic_age_miss_grade_hit(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.min_grade = "k"
        self.config.max_grade = "5"
        self.config.save()
        # 4-year-old in kindergarten — outside age but matches grade
        child = Person.objects.create(
            first_name="Mia", last_name="Lee",
            birthdate=date.today() - timedelta(days=365 * 4),
            grade="k",
        )
        self.assertTrue(is_person_eligible(child, self.config))

    def test_or_logic_group_hit_age_miss(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.save()
        group = Group.objects.create(name="Helpers", category="volunteer")
        self.config.groups.add(group)
        adult = Person.objects.create(
            first_name="Dan", last_name="Lee",
            birthdate=date.today() - timedelta(days=365 * 40),
        )
        GroupMembership.objects.create(group=group, person=adult)
        self.assertTrue(is_person_eligible(adult, self.config))

    def test_person_without_birthdate_skips_age_check(self):
        self.config.min_age = 5
        self.config.max_age = 10
        self.config.save()
        person = Person.objects.create(first_name="Unknown", last_name="Age")
        self.assertFalse(is_person_eligible(person, self.config))

    def test_person_without_grade_skips_grade_check(self):
        self.config.min_grade = "k"
        self.config.max_grade = "5"
        self.config.save()
        person = Person.objects.create(first_name="No", last_name="Grade")
        self.assertFalse(is_person_eligible(person, self.config))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test checkin.tests.test_eligibility -v2`
Expected: ImportError — `checkin.services.eligibility` not found

- [ ] **Step 4: Implement eligibility service**

Create `anchorpoint/checkin/services/eligibility.py`:

```python
from people.models import Person


# Ordered list for grade comparison
GRADE_ORDER = [
    "pre-k", "k", "1", "2", "3", "4", "5", "6",
    "7", "8", "9", "10", "11", "12",
]


def _grade_index(grade):
    """Return numeric index for grade comparison, or -1 if unknown."""
    try:
        return GRADE_ORDER.index(grade)
    except ValueError:
        return -1


def is_person_eligible(person, config):
    """
    Check if a person is eligible for a check-in configuration.

    All filters are optional. If none are set, everyone is eligible.
    When filters are set, OR logic applies — matching ANY filter qualifies.
    """
    has_age = config.min_age is not None or config.max_age is not None
    has_grade = bool(config.min_grade) or bool(config.max_grade)
    has_groups = config.groups.exists()

    if not has_age and not has_grade and not has_groups:
        return True

    if has_age and person.age is not None:
        min_ok = config.min_age is None or person.age >= config.min_age
        max_ok = config.max_age is None or person.age <= config.max_age
        if min_ok and max_ok:
            return True

    if has_grade and person.grade:
        person_idx = _grade_index(person.grade)
        min_idx = _grade_index(config.min_grade) if config.min_grade else 0
        max_idx = _grade_index(config.max_grade) if config.max_grade else len(GRADE_ORDER) - 1
        if person_idx >= 0 and min_idx <= person_idx <= max_idx:
            return True

    if has_groups:
        if person.group_memberships.filter(group__in=config.groups.all()).exists():
            return True

    return False


def get_eligible_members(household, config):
    """Return list of (person, eligible) tuples for all household members."""
    members = household.members.all().select_related()
    results = []
    for person in members:
        results.append((person, is_person_eligible(person, config)))
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test checkin.tests.test_eligibility -v2`
Expected: All 11 tests PASS

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/checkin/services/eligibility.py anchorpoint/checkin/tests/
git commit -m "feat: add eligibility service with OR-logic filters

Supports age range, grade range, and group membership filters.
All optional — no filters means everyone eligible. OR logic
ensures inclusive matching to avoid gaps."
```

---

## Task 5: Create Session Manager Service

**Files:**
- Create: `anchorpoint/checkin/services/session_manager.py`
- Create: `anchorpoint/checkin/tests/test_session_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `anchorpoint/checkin/tests/test_session_manager.py`:

```python
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
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
            day_of_week=now.weekday(),
            checkin_opens=(now - timedelta(hours=1)).time(),
            event_starts=now.time(),
            checkin_closes=(now + timedelta(hours=1)).time(),
            event_ends=(now + timedelta(hours=2)).time(),
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test checkin.tests.test_session_manager -v2`
Expected: ImportError

- [ ] **Step 3: Implement session manager**

Create `anchorpoint/checkin/services/session_manager.py`:

```python
from django.utils import timezone

from checkin.models import CheckInSession


def get_or_create_session(config, window, user=None):
    """
    Get or create a CheckInSession for today from a config + window.

    If a session already exists for this config+window+date, return it.
    Otherwise create one with times copied from the window and rooms from the config.
    """
    today = timezone.localdate()

    session = CheckInSession.objects.filter(
        configuration=config,
        window=window,
        date=today,
    ).first()

    if session:
        return session

    session = CheckInSession.objects.create(
        configuration=config,
        window=window,
        name=config.name,
        date=today,
        checkin_opens=window.checkin_opens,
        checkin_closes=window.checkin_closes,
        event_starts=window.event_starts,
        event_ends=window.event_ends,
        created_by=user,
    )
    session.rooms.set(config.rooms.all())
    return session
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test checkin.tests.test_session_manager -v2`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add anchorpoint/checkin/services/session_manager.py anchorpoint/checkin/tests/test_session_manager.py
git commit -m "feat: add session manager to auto-create sessions from config+window

Gets or creates a CheckInSession for today, copying times from the
window and rooms from the configuration."
```

---

## Task 6: Create Quick Registration Service

**Files:**
- Create: `anchorpoint/checkin/services/quick_registration.py`
- Create: `anchorpoint/checkin/tests/test_quick_registration.py`

- [ ] **Step 1: Write the failing tests**

Create `anchorpoint/checkin/tests/test_quick_registration.py`:

```python
from datetime import date

from django.test import TestCase

from checkin.services.quick_registration import register_new_family
from households.models import Household, HouseholdMember
from people.models import Person


class QuickRegistrationTests(TestCase):
    def test_creates_parent_and_child(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            parent_email="sarah@example.com",
            phone_opt_in=True,
            children=[
                {
                    "first_name": "Mia",
                    "last_name": "Martinez",
                    "birthdate": date(2019, 5, 15),
                    "allergies": "Peanuts",
                    "custody_flag": False,
                    "custody_notes": "",
                    "unauthorized_pickup": "",
                },
            ],
        )
        self.assertIsInstance(result["household"], Household)
        self.assertIsInstance(result["parent"], Person)
        self.assertEqual(len(result["children"]), 1)

    def test_parent_fields_populated(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            parent_email="sarah@example.com",
            phone_opt_in=True,
            children=[
                {"first_name": "Mia", "last_name": "Martinez", "birthdate": date(2019, 5, 15)},
            ],
        )
        parent = result["parent"]
        self.assertEqual(parent.first_name, "Sarah")
        self.assertEqual(parent.last_name, "Martinez")
        self.assertEqual(parent.normalized_phone, "5551234567")
        self.assertEqual(parent.email, "sarah@example.com")
        self.assertTrue(parent.phone_opt_in)

    def test_child_fields_populated(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            children=[
                {
                    "first_name": "Mia",
                    "last_name": "Martinez",
                    "birthdate": date(2019, 5, 15),
                    "allergies": "Tree nuts",
                    "custody_flag": True,
                    "custody_notes": "Mother has sole custody",
                    "unauthorized_pickup": "James Martinez",
                },
            ],
        )
        child = result["children"][0]
        self.assertEqual(child.allergies, "Tree nuts")
        self.assertTrue(child.custody_flag)
        self.assertIn("sole custody", child.custody_notes)

    def test_household_created_with_members(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            children=[
                {"first_name": "Mia", "last_name": "Martinez", "birthdate": date(2019, 5, 15)},
                {"first_name": "Leo", "last_name": "Martinez", "birthdate": date(2021, 3, 10)},
            ],
        )
        household = result["household"]
        self.assertEqual(household.name, "Martinez Family")
        self.assertEqual(household.primary_adult, result["parent"])
        self.assertEqual(household.members.count(), 3)  # parent + 2 children

    def test_multiple_children(self):
        result = register_new_family(
            parent_first="Sarah",
            parent_last="Martinez",
            parent_phone="5551234567",
            children=[
                {"first_name": "Mia", "last_name": "Martinez", "birthdate": date(2019, 5, 15)},
                {"first_name": "Leo", "last_name": "Martinez", "birthdate": date(2021, 3, 10)},
            ],
        )
        self.assertEqual(len(result["children"]), 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test checkin.tests.test_quick_registration -v2`
Expected: ImportError

- [ ] **Step 3: Implement quick registration service**

Create `anchorpoint/checkin/services/quick_registration.py`:

```python
from django.db import transaction

from households.models import Household, HouseholdMember
from people.models import Person


@transaction.atomic
def register_new_family(
    parent_first,
    parent_last,
    parent_phone,
    parent_email="",
    phone_opt_in=False,
    children=None,
):
    """
    Create Person + Household records for a new family at the kiosk.

    Returns dict with keys: household, parent, children (list of Person).
    """
    children = children or []

    parent = Person.objects.create(
        first_name=parent_first,
        last_name=parent_last,
        phone=parent_phone,
        email=parent_email,
        phone_opt_in=phone_opt_in,
    )

    household = Household.objects.create(
        name=f"{parent_last} Family",
        phone=parent_phone,
        primary_adult=parent,
    )

    HouseholdMember.objects.create(
        household=household,
        person=parent,
        relationship_type=HouseholdMember.RelationshipType.ADULT,
    )

    child_records = []
    for child_data in children:
        child = Person.objects.create(
            first_name=child_data["first_name"],
            last_name=child_data.get("last_name", parent_last),
            birthdate=child_data.get("birthdate"),
            allergies=child_data.get("allergies", ""),
            custody_flag=child_data.get("custody_flag", False),
            custody_notes=child_data.get("custody_notes", ""),
            unauthorized_pickup=child_data.get("unauthorized_pickup", ""),
        )
        HouseholdMember.objects.create(
            household=household,
            person=child,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        child_records.append(child)

    return {
        "household": household,
        "parent": parent,
        "children": child_records,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test checkin.tests.test_quick_registration -v2`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add anchorpoint/checkin/services/quick_registration.py anchorpoint/checkin/tests/test_quick_registration.py
git commit -m "feat: add quick registration service for new families

Creates Person records for parent and children, creates Household
with parent as primary_adult and all members linked. Supports
allergies and custody flag data."
```

---

## Task 7: Update Forms for New Kiosk Flow

**Files:**
- Modify: `anchorpoint/checkin/forms.py`

- [ ] **Step 1: Rewrite forms.py**

Replace the contents of `anchorpoint/checkin/forms.py` with:

```python
from django import forms
from django.forms import inlineformset_factory

from .models import CheckInConfiguration, CheckInSession, CheckInWindow, Room, PrinterConfiguration


class CheckInConfigurationForm(forms.ModelForm):
    class Meta:
        model = CheckInConfiguration
        fields = [
            "name", "description", "welcome_message", "location_name",
            "is_active", "rooms", "min_age", "max_age", "min_grade",
            "max_grade", "groups",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "rooms": forms.CheckboxSelectMultiple,
            "groups": forms.CheckboxSelectMultiple,
        }


class CheckInWindowForm(forms.ModelForm):
    class Meta:
        model = CheckInWindow
        fields = [
            "schedule_type", "day_of_week", "specific_date",
            "checkin_opens", "event_starts", "checkin_closes", "event_ends",
            "is_active", "notes",
        ]
        widgets = {
            "specific_date": forms.DateInput(attrs={"type": "date"}),
            "checkin_opens": forms.TimeInput(attrs={"type": "time"}),
            "event_starts": forms.TimeInput(attrs={"type": "time"}),
            "checkin_closes": forms.TimeInput(attrs={"type": "time"}),
            "event_ends": forms.TimeInput(attrs={"type": "time"}),
        }


CheckInWindowFormSet = inlineformset_factory(
    CheckInConfiguration,
    CheckInWindow,
    form=CheckInWindowForm,
    extra=1,
    min_num=1,
    validate_min=True,
    can_delete=True,
)


class KioskPinForm(forms.Form):
    pin = forms.CharField(max_length=6, widget=forms.PasswordInput)

    def __init__(self, *args, expected_pin=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_pin = expected_pin

    def clean_pin(self):
        pin = self.cleaned_data["pin"]
        if self.expected_pin and pin != self.expected_pin:
            raise forms.ValidationError("Incorrect PIN.")
        return pin


class KioskLookupForm(forms.Form):
    query = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            "placeholder": "Last name or phone number",
            "autofocus": True,
            "autocomplete": "off",
        }),
    )


class FamilyMemberSelectForm(forms.Form):
    """Dynamic form for selecting family members and rooms at check-in."""

    def __init__(self, *args, members_with_eligibility=None, rooms=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.members_with_eligibility = members_with_eligibility or []
        room_choices = [(r.pk, str(r)) for r in (rooms or [])]

        for person, eligible in self.members_with_eligibility:
            if eligible:
                self.fields[f"select_{person.pk}"] = forms.BooleanField(
                    required=False, label=str(person)
                )
                self.fields[f"room_{person.pk}"] = forms.ChoiceField(
                    choices=room_choices, required=False
                )

    def get_selected(self):
        """Return list of (person_id, room_id) for selected members."""
        selected = []
        for person, eligible in self.members_with_eligibility:
            if eligible and self.cleaned_data.get(f"select_{person.pk}"):
                room_id = self.cleaned_data.get(f"room_{person.pk}")
                selected.append((person.pk, int(room_id) if room_id else None))
        return selected


class QuickRegistrationForm(forms.Form):
    parent_first_name = forms.CharField(max_length=150)
    parent_last_name = forms.CharField(max_length=150)
    parent_phone = forms.CharField(max_length=20)
    parent_email = forms.EmailField(required=False)
    phone_opt_in = forms.BooleanField(required=False)


class QuickRegistrationChildForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    birthdate = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    allergies = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    custody_flag = forms.BooleanField(required=False)
    custody_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    unauthorized_pickup = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class CheckInSessionForm(forms.ModelForm):
    class Meta:
        model = CheckInSession
        fields = [
            "name", "date", "checkin_opens", "checkin_closes",
            "event_starts", "event_ends", "rooms", "is_active",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "checkin_opens": forms.TimeInput(attrs={"type": "time"}),
            "checkin_closes": forms.TimeInput(attrs={"type": "time"}),
            "event_starts": forms.TimeInput(attrs={"type": "time"}),
            "event_ends": forms.TimeInput(attrs={"type": "time"}),
            "rooms": forms.CheckboxSelectMultiple,
        }


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name", "building", "capacity", "sort_order", "is_active"]


class PrinterConfigForm(forms.ModelForm):
    class Meta:
        model = PrinterConfiguration
        fields = "__all__"


class SecurityCodeLookupForm(forms.Form):
    security_code = forms.CharField(max_length=8)

    def clean_security_code(self):
        return self.cleaned_data["security_code"].upper().strip()
```

- [ ] **Step 2: Commit**

```bash
git add anchorpoint/checkin/forms.py
git commit -m "feat: update checkin forms for new kiosk flow

Adds CheckInConfigurationForm, CheckInWindowFormSet, KioskPinForm,
KioskLookupForm, FamilyMemberSelectForm, QuickRegistrationForm, and
QuickRegistrationChildForm. Updates CheckInSessionForm for new time fields."
```

---

## Task 8: Rewrite Kiosk Views

**Files:**
- Modify: `anchorpoint/checkin/views.py`
- Modify: `anchorpoint/checkin/urls.py`

This is the largest task. The kiosk views need to be rewritten for the new flow.

- [ ] **Step 1: Rewrite kiosk views in views.py**

Replace the kiosk section of `anchorpoint/checkin/views.py` (the functions `kiosk_home`, `kiosk_lookup`, `kiosk_select`, `kiosk_rooms`, `kiosk_complete`) with the new flow. Keep the admin/dashboard/checkout views. Add the config admin views.

The kiosk views should implement:

```python
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from core.models import OrganizationSettings
from core.permissions import checkin_admin_required, staff_required
from households.models import Household
from people.models import Person, normalize_phone

from .forms import (
    CheckInConfigurationForm, CheckInWindowFormSet, CheckInSessionForm,
    FamilyMemberSelectForm, KioskLookupForm, KioskPinForm,
    QuickRegistrationForm, QuickRegistrationChildForm,
    RoomForm, PrinterConfigForm, SecurityCodeLookupForm,
)
from .models import (
    CheckIn, CheckInConfiguration, CheckInSession, CheckInWindow,
    Room, PrinterConfiguration, generate_security_code,
)
from .services.eligibility import get_eligible_members
from .services.session_manager import get_or_create_session
from .services.quick_registration import register_new_family


KIOSK_SESSION_KEY = "kiosk_authenticated"
KIOSK_SESSION_ID_KEY = "kiosk_session_id"


def _ensure_kiosk(request):
    """Redirect to unlock if kiosk not authenticated."""
    if not request.session.get(KIOSK_SESSION_KEY):
        return redirect("checkin:kiosk_unlock")
    return None


def _get_active_session(request):
    """Get the active CheckInSession from the kiosk session."""
    session_id = request.session.get(KIOSK_SESSION_ID_KEY)
    if session_id:
        return CheckInSession.objects.filter(pk=session_id, is_active=True).first()
    return None


# ── Kiosk Views (public, PIN-gated) ──

def kiosk_unlock(request):
    org = OrganizationSettings.load()
    if request.method == "POST":
        form = KioskPinForm(request.POST, expected_pin=org.kiosk_pin)
        if form.is_valid():
            request.session[KIOSK_SESSION_KEY] = True
            return redirect("checkin:kiosk_lookup")
    else:
        form = KioskPinForm()
    return render(request, "checkin/kiosk/unlock.html", {"form": form, "org": org})


def kiosk_lookup(request):
    redir = _ensure_kiosk(request)
    if redir:
        return redir

    org = OrganizationSettings.load()

    # Find open configurations
    now = timezone.localtime()
    open_configs = []
    for config in CheckInConfiguration.objects.filter(is_active=True):
        windows = config.open_windows(now)
        if windows:
            open_configs.append((config, windows[0]))

    if not open_configs:
        next_window = _next_upcoming_window()
        return render(request, "checkin/kiosk/no_sessions.html", {
            "org": org, "next_window": next_window,
        })

    # Auto-select if only one config is open
    if len(open_configs) == 1:
        config, window = open_configs[0]
        session = get_or_create_session(config, window)
        request.session[KIOSK_SESSION_ID_KEY] = session.pk
    # TODO: if multiple configs open, show picker (future enhancement)

    session = _get_active_session(request)
    if not session:
        return redirect("checkin:kiosk_unlock")

    households = []
    query = ""
    if request.method == "GET" and "query" in request.GET:
        form = KioskLookupForm(request.GET)
        if form.is_valid():
            query = form.cleaned_data["query"]
            digits = normalize_phone(query)
            if len(digits) >= 7:
                households = Household.objects.filter(
                    members__normalized_phone__endswith=digits[-10:]
                ).distinct()
            else:
                households = Household.objects.filter(
                    name__icontains=query
                ) | Household.objects.filter(
                    members__last_name__icontains=query
                )
                households = households.distinct()
    else:
        form = KioskLookupForm()

    return render(request, "checkin/kiosk/lookup_new.html", {
        "form": form,
        "households": households,
        "query": query,
        "session": session,
        "org": org,
    })


def kiosk_family_select(request, household_id):
    redir = _ensure_kiosk(request)
    if redir:
        return redir

    session = _get_active_session(request)
    if not session or not session.configuration:
        return redirect("checkin:kiosk_lookup")

    household = get_object_or_404(Household, pk=household_id)
    config = session.configuration
    members_with_eligibility = get_eligible_members(household, config)
    rooms = list(session.rooms.all())

    if request.method == "POST":
        form = FamilyMemberSelectForm(
            request.POST,
            members_with_eligibility=members_with_eligibility,
            rooms=rooms,
        )
        if form.is_valid():
            selected = form.get_selected()
            if not selected:
                form.add_error(None, "Please select at least one person.")
            else:
                security_code = generate_security_code()
                checkin_ids = []
                for person_id, room_id in selected:
                    person = Person.objects.get(pk=person_id)
                    room = Room.objects.get(pk=room_id) if room_id else None
                    checkin, created = CheckIn.objects.get_or_create(
                        session=session,
                        person=person,
                        defaults={
                            "room": room,
                            "security_code": security_code,
                        },
                    )
                    if created:
                        checkin_ids.append(checkin.pk)

                request.session["kiosk_checkin_ids"] = checkin_ids
                request.session["kiosk_security_code"] = security_code
                return redirect("checkin:kiosk_confirmation")
    else:
        form = FamilyMemberSelectForm(
            members_with_eligibility=members_with_eligibility,
            rooms=rooms,
        )

    return render(request, "checkin/kiosk/family_select.html", {
        "household": household,
        "form": form,
        "members_with_eligibility": members_with_eligibility,
        "rooms": rooms,
        "session": session,
        "config": config,
    })


def kiosk_confirmation(request):
    redir = _ensure_kiosk(request)
    if redir:
        return redir

    checkin_ids = request.session.pop("kiosk_checkin_ids", [])
    security_code = request.session.pop("kiosk_security_code", "")
    checkins = CheckIn.objects.filter(pk__in=checkin_ids).select_related("person", "room")
    org = OrganizationSettings.load()
    session = _get_active_session(request)

    return render(request, "checkin/kiosk/confirmation.html", {
        "checkins": checkins,
        "security_code": security_code,
        "session": session,
        "org": org,
    })


def kiosk_quick_register(request):
    redir = _ensure_kiosk(request)
    if redir:
        return redir

    org = OrganizationSettings.load()

    if request.method == "POST":
        parent_form = QuickRegistrationForm(request.POST)
        # Parse child forms from POST data
        child_count = int(request.POST.get("child_count", "1"))
        child_forms = []
        children_valid = True
        for i in range(child_count):
            prefix = f"child_{i}"
            cf = QuickRegistrationChildForm(request.POST, prefix=prefix)
            child_forms.append(cf)
            if not cf.is_valid():
                children_valid = False

        if parent_form.is_valid() and children_valid:
            children_data = []
            for cf in child_forms:
                child_data = {
                    "first_name": cf.cleaned_data["first_name"],
                    "last_name": cf.cleaned_data.get("last_name") or parent_form.cleaned_data["parent_last_name"],
                    "birthdate": cf.cleaned_data["birthdate"],
                    "allergies": cf.cleaned_data.get("allergies", ""),
                    "custody_flag": cf.cleaned_data.get("custody_flag", False),
                    "custody_notes": cf.cleaned_data.get("custody_notes", ""),
                    "unauthorized_pickup": cf.cleaned_data.get("unauthorized_pickup", ""),
                }
                children_data.append(child_data)

            result = register_new_family(
                parent_first=parent_form.cleaned_data["parent_first_name"],
                parent_last=parent_form.cleaned_data["parent_last_name"],
                parent_phone=parent_form.cleaned_data["parent_phone"],
                parent_email=parent_form.cleaned_data.get("parent_email", ""),
                phone_opt_in=parent_form.cleaned_data.get("phone_opt_in", False),
                children=children_data,
            )
            return redirect("checkin:kiosk_family_select", household_id=result["household"].pk)
    else:
        parent_form = QuickRegistrationForm()
        child_forms = [QuickRegistrationChildForm(prefix="child_0")]

    return render(request, "checkin/kiosk/quick_register.html", {
        "parent_form": parent_form,
        "child_forms": child_forms,
        "org": org,
    })


def kiosk_lock(request):
    request.session.pop(KIOSK_SESSION_KEY, None)
    request.session.pop(KIOSK_SESSION_ID_KEY, None)
    return redirect("checkin:kiosk_unlock")


def _next_upcoming_window():
    """Find the next check-in window that will open."""
    now = timezone.localtime()
    windows = CheckInWindow.objects.filter(
        is_active=True, configuration__is_active=True
    )
    for w in windows:
        if w.schedule_type == CheckInWindow.TYPE_SPECIFIC_DATE:
            if w.specific_date and w.specific_date >= now.date():
                return w
        else:
            return w
    return None


# ── Configuration Admin Views ──

@checkin_admin_required
def configuration_list(request):
    configs = CheckInConfiguration.objects.prefetch_related("windows", "rooms", "groups")
    return render(request, "checkin/config_list.html", {"configurations": configs})


@checkin_admin_required
def configuration_create(request):
    return _config_form(request, instance=None)


@checkin_admin_required
def configuration_edit(request, pk):
    config = get_object_or_404(CheckInConfiguration, pk=pk)
    return _config_form(request, instance=config)


def _config_form(request, instance):
    if request.method == "POST":
        form = CheckInConfigurationForm(request.POST, instance=instance)
        formset = CheckInWindowFormSet(request.POST, instance=instance or CheckInConfiguration())
        if form.is_valid() and formset.is_valid():
            config = form.save()
            formset.instance = config
            formset.save()
            return redirect("checkin:configuration_list")
    else:
        form = CheckInConfigurationForm(instance=instance)
        formset = CheckInWindowFormSet(instance=instance or CheckInConfiguration())
    return render(request, "checkin/config_form.html", {
        "form": form,
        "formset": formset,
        "editing": instance is not None,
    })
```

- [ ] **Step 2: Update URLs**

Replace `anchorpoint/checkin/urls.py` contents with:

```python
from django.urls import path

from . import views

app_name = "checkin"

urlpatterns = [
    # Kiosk (public, PIN-gated)
    path("kiosk/", views.kiosk_lookup, name="kiosk_lookup"),
    path("kiosk/unlock/", views.kiosk_unlock, name="kiosk_unlock"),
    path("kiosk/lock/", views.kiosk_lock, name="kiosk_lock"),
    path("kiosk/family/<int:household_id>/", views.kiosk_family_select, name="kiosk_family_select"),
    path("kiosk/confirmation/", views.kiosk_confirmation, name="kiosk_confirmation"),
    path("kiosk/register/", views.kiosk_quick_register, name="kiosk_quick_register"),

    # Checkout (login required)
    path("checkout/<int:session_id>/", views.checkout_lookup, name="checkout_lookup"),
    path("checkout/<int:session_id>/confirm/", views.checkout_confirm, name="checkout_confirm"),

    # Configuration admin (checkin_admin_required)
    path("configurations/", views.configuration_list, name="configuration_list"),
    path("configurations/new/", views.configuration_create, name="configuration_create"),
    path("configurations/<int:pk>/", views.configuration_edit, name="configuration_edit"),

    # Dashboard and admin (staff_required)
    path("", views.dashboard, name="dashboard"),
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/new/", views.session_create, name="session_create"),
    path("sessions/<int:session_id>/", views.session_detail, name="session_detail"),
    path("sessions/<int:session_id>/edit/", views.session_edit, name="session_edit"),

    # Room management
    path("rooms/", views.room_list, name="room_list"),
    path("rooms/new/", views.room_create, name="room_create"),
    path("rooms/<int:room_id>/edit/", views.room_edit, name="room_edit"),

    # Printer management
    path("printers/", views.printer_list, name="printer_list"),
    path("printers/new/", views.printer_create, name="printer_create"),
    path("printers/<int:printer_id>/edit/", views.printer_edit, name="printer_edit"),
    path("printers/<int:printer_id>/test/", views.printer_test, name="printer_test"),

    # API
    path("api/sessions/<int:session_id>/stats/", views.api_session_stats, name="api_session_stats"),
]
```

- [ ] **Step 3: Commit**

```bash
git add anchorpoint/checkin/views.py anchorpoint/checkin/urls.py
git commit -m "feat: rewrite kiosk views for new check-in flow

New flow: PIN unlock → family lookup → member selection with
eligibility + room pick → confirmation with print trigger.
Adds quick registration for new families and configuration
admin views with checkin_admin_required permission."
```

---

## Task 9: Create Kiosk Templates

**Files:**
- Create: all template files in `anchorpoint/checkin/templates/checkin/kiosk/` and `checkin/labels/`

This task creates the HTML templates. Each template should extend the kiosk base and use the Outfit font.

- [ ] **Step 1: Create kiosk base template**

Update `anchorpoint/checkin/templates/checkin/kiosk/base.html` to include the Outfit font and dark theme styling matching the mockups. The base should include:
- Google Fonts link for Outfit
- Dark theme CSS (`background: #0a0a14`, white text)
- CSS `@media print` rules that hide everything except `.print-labels`
- `@page` rule setting 62mm width
- Touch-friendly sizing (large tap targets, 16px minimum text)

- [ ] **Step 2: Create unlock.html**

`anchorpoint/checkin/templates/checkin/kiosk/unlock.html` — PIN entry with org logo/name, numeric keypad. POST form to `kiosk_unlock` URL.

- [ ] **Step 3: Create lookup_new.html**

`anchorpoint/checkin/templates/checkin/kiosk/lookup_new.html` — search field, household results as cards showing family name + member summary, "I'm New Here" button linking to `kiosk_quick_register`.

- [ ] **Step 4: Create family_select.html**

`anchorpoint/checkin/templates/checkin/kiosk/family_select.html` — household member list with checkboxes for eligible members, room picker buttons, ✚/shield indicators. POST form to `kiosk_family_select`.

- [ ] **Step 5: Create confirmation.html**

`anchorpoint/checkin/templates/checkin/kiosk/confirmation.html` — success screen with security code, checked-in list, auto-redirect JS timer. Hidden `.print-labels` div with child and pickup label HTML. `window.print()` on load.

- [ ] **Step 6: Create quick_register.html**

`anchorpoint/checkin/templates/checkin/kiosk/quick_register.html` — parent fields, child fields (repeatable), SMS opt-in checkbox, custody checkbox with expandable section. JS to add/remove child forms.

- [ ] **Step 7: Create no_sessions.html**

`anchorpoint/checkin/templates/checkin/kiosk/no_sessions.html` — "Check-in is not currently open" message with next window time if available.

- [ ] **Step 8: Create label templates**

`anchorpoint/checkin/templates/checkin/labels/child_label.html`:
```html
<div class="label child-label">
  <div class="label-top">
    <div class="label-name">{{ checkin.person.first_name }} {{ checkin.person.last_name }}</div>
    <div class="label-room">{{ checkin.room }} · {{ checkin.person.grade|default:"" }}</div>
  </div>
  <div class="label-bottom">
    <div class="label-session">{{ session.name }} · {{ session.date|date:"M j" }}</div>
    <div class="label-code-area">
      {% if checkin.person.allergies %}<span class="label-icon">✚</span>{% endif %}
      {% if checkin.person.custody_flag %}<span class="label-icon"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 2L3 7v5c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-9-5z" fill="currentColor"/></svg></span>{% endif %}
      <div class="label-code">{{ checkin.security_code }}</div>
    </div>
  </div>
</div>
```

`anchorpoint/checkin/templates/checkin/labels/pickup_label.html`:
```html
<div class="label pickup-label">
  <div class="label-header">Pickup Tag</div>
  <div class="label-code-large">{{ security_code }}</div>
  <div class="label-children">{{ children_names }}</div>
  <div class="label-session">{{ session.name }} · {{ session.date|date:"M j" }}</div>
</div>
```

- [ ] **Step 9: Commit**

```bash
git add anchorpoint/checkin/templates/
git commit -m "feat: add kiosk and label templates with dark theme and Outfit font

Includes unlock, lookup, family select, confirmation, quick register,
no sessions, and label templates. CSS @media print hides kiosk UI
and prints labels at 62mm width."
```

---

## Task 10: Create Configuration Admin Templates

**Files:**
- Create: `anchorpoint/checkin/templates/checkin/config_list.html`
- Create: `anchorpoint/checkin/templates/checkin/config_form.html`

- [ ] **Step 1: Create config_list.html**

List all configurations with name, schedule summary, room count, group count, active status. Links to create/edit.

- [ ] **Step 2: Create config_form.html**

Form with inline window formset. Should include JS to toggle schedule_type fields (day_of_week vs specific_date) and dynamically add/remove windows.

- [ ] **Step 3: Commit**

```bash
git add anchorpoint/checkin/templates/checkin/config_list.html anchorpoint/checkin/templates/checkin/config_form.html
git commit -m "feat: add configuration admin templates for check-in management"
```

---

## Task 11: Remove attendance/ App

**Files:**
- Delete: `anchorpoint/attendance/` (entire directory)
- Modify: `anchorpoint/anchorpoint/settings.py`
- Modify: `anchorpoint/anchorpoint/urls.py`

- [ ] **Step 1: Remove attendance from INSTALLED_APPS**

In `anchorpoint/anchorpoint/settings.py`, remove `"attendance"` from INSTALLED_APPS.

- [ ] **Step 2: Remove attendance URL include**

In `anchorpoint/anchorpoint/urls.py`, remove:
```python
path("attendance/", include(("attendance.urls", "attendance"), namespace="attendance")),
```

- [ ] **Step 3: Create migration to drop attendance tables**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py makemigrations --empty checkin -n remove_attendance_tables`

Then manually add operations to the migration to drop the old tables if they exist (since Django won't auto-generate this after removing the app):

```python
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ("checkin", "previous_migration"),
    ]

    operations = [
        migrations.RunSQL(
            "DROP TABLE IF EXISTS attendance_attendancerecord CASCADE;",
            migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DROP TABLE IF EXISTS attendance_checkinwindow CASCADE;",
            migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DROP TABLE IF EXISTS attendance_checkinconfiguration_groups CASCADE;",
            migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DROP TABLE IF EXISTS attendance_checkinconfiguration CASCADE;",
            migrations.RunSQL.noop,
        ),
    ]
```

- [ ] **Step 4: Delete attendance/ directory**

```bash
rm -rf anchorpoint/attendance/
```

- [ ] **Step 5: Run migrate and verify**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py migrate`
Then: `cd anchorpoint && ../venv/Scripts/python.exe manage.py check`

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove attendance/ app after migration to checkin/

All scheduling and configuration functionality now lives in
the checkin/ module. Drops old attendance tables."
```

---

## Task 12: Write Kiosk Integration Tests

**Files:**
- Create: `anchorpoint/checkin/tests/test_kiosk_views.py`

- [ ] **Step 1: Write kiosk flow tests**

Create `anchorpoint/checkin/tests/test_kiosk_views.py`:

```python
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from checkin.models import (
    CheckIn, CheckInConfiguration, CheckInSession, CheckInWindow, Room,
)
from core.models import OrganizationSettings
from groups.models import Group, GroupMembership
from households.models import Household, HouseholdMember
from people.models import Person


class KioskFlowTests(TestCase):
    def setUp(self):
        self.config = CheckInConfiguration.objects.create(
            name="Sunday Kids",
            welcome_message="Welcome!",
            location_name="Main Building",
            min_age=3,
            max_age=12,
        )
        self.room = Room.objects.create(name="Room 100")
        self.config.rooms.add(self.room)

        now = timezone.localtime()
        self.window = CheckInWindow.objects.create(
            configuration=self.config,
            schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=now.weekday(),
            checkin_opens=(now - timedelta(hours=1)).time(),
            event_starts=now.time(),
            checkin_closes=(now + timedelta(hours=1)).time(),
            event_ends=(now + timedelta(hours=2)).time(),
        )

        self.household = Household.objects.create(name="Johnson Family", phone="555-123-4567")
        self.parent = Person.objects.create(
            first_name="Mark", last_name="Johnson",
            birthdate=date.today() - timedelta(days=365 * 35),
        )
        self.child = Person.objects.create(
            first_name="Emma", last_name="Johnson",
            birthdate=date.today() - timedelta(days=365 * 8),
            allergies="Peanuts",
        )
        HouseholdMember.objects.create(
            household=self.household, person=self.parent,
            relationship_type=HouseholdMember.RelationshipType.ADULT,
        )
        HouseholdMember.objects.create(
            household=self.household, person=self.child,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )

        org = OrganizationSettings.load()
        org.kiosk_pin = "1234"
        org.save()

    def _unlock(self):
        session = self.client.session
        session["kiosk_authenticated"] = True
        session.save()

    def test_unlock_with_correct_pin(self):
        response = self.client.post(
            reverse("checkin:kiosk_unlock"), {"pin": "1234"}
        )
        self.assertRedirects(response, reverse("checkin:kiosk_lookup"))

    def test_unlock_with_wrong_pin(self):
        response = self.client.post(
            reverse("checkin:kiosk_unlock"), {"pin": "9999"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incorrect PIN")

    def test_lookup_requires_pin(self):
        response = self.client.get(reverse("checkin:kiosk_lookup"))
        self.assertRedirects(response, reverse("checkin:kiosk_unlock"))

    def test_lookup_finds_family(self):
        self._unlock()
        response = self.client.get(
            reverse("checkin:kiosk_lookup"), {"query": "Johnson"}
        )
        self.assertContains(response, "Johnson Family")

    def test_family_select_shows_eligible_members(self):
        self._unlock()
        # First hit lookup to create session
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Johnson"})
        response = self.client.get(
            reverse("checkin:kiosk_family_select", args=[self.household.pk])
        )
        self.assertContains(response, "Emma Johnson")

    def test_checkin_creates_records(self):
        self._unlock()
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Johnson"})
        response = self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {
                f"select_{self.child.pk}": "on",
                f"room_{self.child.pk}": str(self.room.pk),
            },
        )
        self.assertRedirects(response, reverse("checkin:kiosk_confirmation"))
        self.assertTrue(CheckIn.objects.filter(person=self.child).exists())

    def test_confirmation_shows_security_code(self):
        self._unlock()
        self.client.get(reverse("checkin:kiosk_lookup"), {"query": "Johnson"})
        self.client.post(
            reverse("checkin:kiosk_family_select", args=[self.household.pk]),
            {
                f"select_{self.child.pk}": "on",
                f"room_{self.child.pk}": str(self.room.pk),
            },
        )
        # Security code was stored in session, follow redirect
        checkin = CheckIn.objects.get(person=self.child)
        self.assertEqual(len(checkin.security_code), 4)


class QuickRegistrationViewTests(TestCase):
    def setUp(self):
        self.config = CheckInConfiguration.objects.create(name="Open Check-In")
        self.room = Room.objects.create(name="Room A")
        self.config.rooms.add(self.room)
        now = timezone.localtime()
        CheckInWindow.objects.create(
            configuration=self.config,
            schedule_type=CheckInWindow.TYPE_WEEKLY,
            day_of_week=now.weekday(),
            checkin_opens=(now - timedelta(hours=1)).time(),
            event_starts=now.time(),
            checkin_closes=(now + timedelta(hours=1)).time(),
            event_ends=(now + timedelta(hours=2)).time(),
        )
        org = OrganizationSettings.load()
        org.kiosk_pin = "1234"
        org.save()

    def _unlock(self):
        session = self.client.session
        session["kiosk_authenticated"] = True
        session.save()

    def test_quick_register_creates_family(self):
        self._unlock()
        self.client.get(reverse("checkin:kiosk_lookup"))
        response = self.client.post(
            reverse("checkin:kiosk_quick_register"),
            {
                "parent_first_name": "Sarah",
                "parent_last_name": "Martinez",
                "parent_phone": "5551234567",
                "parent_email": "sarah@test.com",
                "phone_opt_in": "on",
                "child_count": "1",
                "child_0-first_name": "Mia",
                "child_0-last_name": "Martinez",
                "child_0-birthdate": "2019-05-15",
            },
        )
        self.assertTrue(Person.objects.filter(first_name="Sarah", last_name="Martinez").exists())
        self.assertTrue(Person.objects.filter(first_name="Mia", last_name="Martinez").exists())
        self.assertTrue(Household.objects.filter(name="Martinez Family").exists())
        household = Household.objects.get(name="Martinez Family")
        self.assertRedirects(
            response,
            reverse("checkin:kiosk_family_select", args=[household.pk]),
        )
```

- [ ] **Step 2: Run tests**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test checkin.tests.test_kiosk_views -v2`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add anchorpoint/checkin/tests/test_kiosk_views.py
git commit -m "test: add kiosk flow and quick registration integration tests"
```

---

## Task 13: Update Room Form and Admin Views

**Files:**
- Modify: `anchorpoint/checkin/views.py` (room_create, room_edit)
- Modify: `anchorpoint/checkin/templates/checkin/room_form.html`

- [ ] **Step 1: Update room form template**

Remove the age/grade fields from `anchorpoint/checkin/templates/checkin/room_form.html`. The RoomForm in forms.py already only includes `name, building, capacity, sort_order, is_active`.

- [ ] **Step 2: Run full test suite**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test -v2`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add anchorpoint/checkin/templates/checkin/room_form.html
git commit -m "fix: remove age/grade fields from room form template"
```

---

## Task 14: Final Verification

- [ ] **Step 1: Run all migrations**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py migrate`

- [ ] **Step 2: Run system check**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py check`
Expected: System check identified no issues.

- [ ] **Step 3: Run full test suite**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py test -v2`
Expected: All tests PASS

- [ ] **Step 4: Start dev server and test kiosk flow manually**

Run: `cd anchorpoint && ../venv/Scripts/python.exe manage.py runserver`

Test the following:
1. Navigate to `/checkin/kiosk/unlock/` — enter PIN
2. Search for a family by last name
3. Select eligible members and pick rooms
4. Verify confirmation screen shows security code
5. Test "I'm New Here" quick registration flow
6. Verify labels render in print preview (Ctrl+P)
7. Test `/checkin/configurations/` admin interface

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found during manual kiosk testing"
```
