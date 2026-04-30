# Check-In Kiosk System — Design Spec

## Overview

A unified check-in kiosk system for AnchorPoint that consolidates the existing `attendance/` and `checkin/` apps into a single `checkin/` module. Supports children's ministry, volunteer teams, event attendees, and any scenario requiring check-in with label printing.

Families use a tablet in Chrome kiosk mode to look up their household, select eligible members, pick rooms, and print name tags + pickup tags to a thermal label printer (Brother QL-820 or generic Rollo/Nelko-style printers).

## Architecture

Three layers:

1. **Admin Configuration** — staff defines rooms, check-in configurations (schedule + eligibility + rooms), and printer settings
2. **Kiosk Runtime** — tablet-based flow: PIN unlock → family lookup → member selection → room pick → print labels → done
3. **Data Layer** — Person, Household, CheckIn, CheckInSession, CheckInConfiguration, CheckInWindow, Room

### Consolidation: attendance/ → checkin/

Migrate `CheckInConfiguration` and `CheckInWindow` models from `attendance/` into `checkin/`. Delete the `attendance/` app entirely. The `checkin/` app becomes the single source of truth for all check-in functionality.

## Data Model

### Room (simplified from existing)

Physical space only — no eligibility filters.

| Field | Type | Notes |
|-------|------|-------|
| name | CharField | "Classroom 100" |
| building | CharField | optional |
| capacity | IntegerField | optional |
| sort_order | IntegerField | display ordering |
| is_active | BooleanField | |

Removed from existing: `min_age`, `max_age`, `min_grade`, `max_grade`. Rooms are just physical spaces — eligibility lives on the configuration.

### CheckInConfiguration (migrated from attendance/)

Defines what, where, when, and who for a check-in experience.

| Field | Type | Notes |
|-------|------|-------|
| name | CharField | "Sunday Morning Kids" |
| description | TextField | optional |
| welcome_message | TextField | optional, shown on kiosk lookup screen |
| location_name | CharField | "Main Building" |
| is_active | BooleanField | |
| rooms | M2M → Room | ordered list of eligible rooms |
| min_age | IntegerField | optional, eligibility filter |
| max_age | IntegerField | optional, eligibility filter |
| min_grade | CharField (choices) | optional, eligibility filter |
| max_grade | CharField (choices) | optional, eligibility filter |
| groups | M2M → Group | optional, eligibility filter |

### Eligibility Logic

All filters are optional. If no filters are set, anyone can check in. When filters are set, they use **OR logic** — a person is eligible if they match **any** filter:

```
def is_eligible(person, config):
    has_age = config.min_age or config.max_age
    has_grade = config.min_grade or config.max_grade
    has_groups = config.groups.exists()

    # No filters = everyone eligible
    if not has_age and not has_grade and not has_groups:
        return True

    # OR logic — match any filter
    if has_age and person.age and config.min_age <= person.age <= config.max_age:
        return True
    if has_grade and person.grade and config.min_grade <= person.grade <= config.max_grade:
        return True
    if has_groups and person.group_memberships.filter(group__in=config.groups.all()).exists():
        return True

    return False
```

Use cases:
- **Children's ministry:** ages 5-10 OR grades K-5 (either/or, inclusive)
- **Volunteer team:** group = "Sunday Volunteers" (no age/grade)
- **Event attendees:** group = auto-generated event group (no age/grade)
- **Open check-in:** no filters set, anyone can check in

### CheckInWindow (migrated from attendance/)

Schedule windows with four distinct time fields.

| Field | Type | Notes |
|-------|------|-------|
| configuration | FK → CheckInConfiguration | |
| schedule_type | CharField (choices) | `weekly` or `specific_date` |
| day_of_week | IntegerField (0-6) | required for weekly |
| specific_date | DateField | required for specific_date |
| checkin_opens | TimeField | 9:00am — kiosk starts accepting |
| event_starts | TimeField | 10:00am — informational, shown on labels |
| checkin_closes | TimeField | 10:30am — kiosk stops accepting new check-ins |
| event_ends | TimeField | 11:00am — pickup/checkout time |
| is_active | BooleanField | |

Validation: `checkin_opens < checkin_closes` and `event_starts < event_ends` (all four required). Other orderings are flexible — check-in may open before or after event start, and may close before or after event end.

### CheckInSession (existing, modified)

Concrete instance of a configuration + window for a specific date.

| Field | Type | Notes |
|-------|------|-------|
| configuration | FK → CheckInConfiguration | **new** |
| window | FK → CheckInWindow | **new** |
| name | CharField | auto-populated from config name |
| date | DateField | |
| checkin_opens | TimeField | copied from window |
| checkin_closes | TimeField | copied from window |
| event_starts | TimeField | copied from window |
| event_ends | TimeField | copied from window |
| rooms | M2M → Room | copied from config |
| is_active | BooleanField | |
| created_by | FK → User | |

Sessions are created when the kiosk opens and a matching window is active for today. Times are copied from the window so the session is a self-contained snapshot.

### CheckIn (existing, unchanged)

| Field | Type | Notes |
|-------|------|-------|
| session | FK → CheckInSession | |
| person | FK → Person | |
| room | FK → Room | |
| security_code | CharField(4) | shared per family per session |
| checked_in_at | DateTimeField | |
| checked_in_by | FK → User | nullable (null = self-service kiosk) |
| checked_out_at | DateTimeField | nullable |
| checked_out_by | FK → User | nullable |
| child_label_printed | BooleanField | |
| parent_label_printed | BooleanField | |
| notes | TextField | optional |

Security code: 4 random alphanumeric characters, generated once per family per session. All siblings share the same code.

### Person (existing, new fields)

Three new fields for custody/security tracking. Only relevant for minors (`is_minor == True`).

| Field | Type | Notes |
|-------|------|-------|
| custody_flag | BooleanField | default False |
| custody_notes | TextField | blank, shown when custody_flag is True |
| unauthorized_pickup | TextField | blank, people NOT allowed to pick up |

UI only shows these fields when the person is a minor.

### PrinterConfiguration and LabelTemplate (existing, unchanged)

Keep the existing models. The print implementation changes from server-side Pillow rendering to CSS `@media print` browser printing (see Printing section).

## Kiosk Flow

### Screen 1: PIN Unlock

- Organization logo and name (from `OrganizationSettings`)
- Numeric keypad for PIN entry
- PIN stored in `OrganizationSettings.kiosk_pin`
- On success, sets session key and redirects to lookup
- Kiosk stays unlocked until browser is closed or device sleeps

### Screen 2: Family Lookup

- Organization logo/name in header
- Welcome message from active configuration
- Location name from configuration
- Single input field: "Enter your last name or phone number"
- Search matches against `Household.name`, `Person.last_name`, and `Person.normalized_phone`
- Results show household cards with member summary (names + ages)
- "I'm New Here" button for unrecognized families
- If only one active configuration has an open window, use it automatically. If multiple are open, show a picker first.
- If no configurations have open windows, show a friendly message: "Check-in is not currently open" with the next upcoming window time if available.

### Screen 3: Select Family Members

- Shows all household members
- Eligible members (per configuration's eligibility logic) get checkboxes
- Ineligible members shown grayed out with reason ("Adult · Not eligible for this check-in")
- Selected members get room picker buttons (from configuration's room list, ordered by sort_order)
- Discrete indicators on member cards:
  - ✚ (first-aid cross) for allergy — shown when `person.allergies` is non-empty
  - Filled shield (solid SVG) for security — shown when `person.custody_flag` is True
- "Check In N People" submit button
- Back to search link

### Screen 4: Confirmation + Print

- Success checkmark
- "You're All Set!" heading
- "Labels are printing now" subtitle
- Large security code display
- "Present the pickup tag at pickup" instruction
- Summary list: each person + their assigned room
- Labels auto-print via `window.print()` (Chrome kiosk mode `--kiosk-printing`)
- Auto-redirect countdown (8 seconds) back to lookup screen
- Manual "Check in another family" link

### Screen 5: Quick Registration (New Family)

Minimal form for first-time families. Creates real Person + Household records.

**Parent/Guardian fields:**
- First name (required)
- Last name (required)
- Phone number (required)
- Email (optional)
- SMS opt-in checkbox: "Allow SMS updates from [org name]" (maps to `Person.phone_opt_in`)

**Per-child fields (repeatable via "+ Add Another Child"):**
- First name (required)
- Last name (required, pre-filled from parent)
- Birthdate (required)
- Allergies (optional)
- Security/custody concern checkbox (only for minors):
  - When checked, expands to show:
    - Custody notes (free text)
    - Unauthorized pickup persons (free text)

On submit:
1. Create Person records for parent and each child
2. Create Household with parent as primary_adult, all persons as members
3. Redirect to Select Family Members screen (Screen 3) with the new household

**Backlog item:** Automated follow-up workflow to ask new families to complete their profiles (additional address, emergency contacts, etc.)

## Label Design

### Print Implementation

CSS `@media print` approach via browser:

1. Confirmation page includes a hidden `<div class="print-labels">` containing all label HTML
2. CSS `@media print` hides everything except `.print-labels`
3. `@page` rule sets label dimensions (62mm width)
4. Each label is a `page-break-after: always` block
5. Chrome kiosk mode (`--kiosk-printing`) auto-prints to default printer with no dialog
6. `window.print()` fires on page load
7. After print dialog closes, JS redirects back to lookup

Print order: child name tags first, parent pickup tag last.

Designed for smallest common size: Brother QL-820 at 62mm (~2.4") wide. Works on wider printers (Rollo/Nelko 4x6") — labels will be left-aligned with whitespace.

### Child Name Tag (62mm × ~76mm / 2.4" × 3")

```
┌─────────────────────────────────┐
│                                 │
│  Emma Johnson                   │
│  Room 100 · 3rd Grade           │
│                                 │
│                                 │
│  Sunday Morning · Apr 30   ✚    │
│                           XK7M  │
└─────────────────────────────────┘
```

- Name: large bold (Outfit 800)
- Room + grade: smaller, gray
- Session name + date: bottom-left, small gray
- Security code: bottom-right, large bold monospace
- Allergy symbol (✚): above security code, only when `person.allergies` is non-empty
- Security symbol (filled shield): above security code, only when `person.custody_flag` is True
- Both symbols shown side-by-side when both apply

### Parent Pickup Tag (62mm × ~65mm / 2.4" × 2.5")

```
┌─────────────────────────────────┐
│          PICKUP TAG             │
│                                 │
│           XK7M                  │
│                                 │
│   Emma Johnson · Liam Johnson   │
│     Sunday Morning · Apr 30     │
└─────────────────────────────────┘
```

- "Pickup Tag" header: small uppercase
- Security code: centered, very large bold
- Children's names: centered, joined with " · "
- Session + date: centered, small gray

### Typography

Outfit typeface throughout (Google Fonts). Modern geometric sans-serif, clean at all sizes on screen and print.

## Kiosk Setup

### Chrome Kiosk Mode

Tablet or dedicated laptop runs Chrome with:
```
chrome --kiosk --kiosk-printing --disable-pinch --overscroll-history-navigation=0 https://anchorpoint.bolivar.church/checkin/kiosk/
```

- `--kiosk`: fullscreen, no browser UI
- `--kiosk-printing`: auto-prints to default printer, no dialog
- Default printer set to the thermal label printer via OS settings

### Printer Setup

- **Brother QL-820:** USB connection, standard print driver, 62mm continuous roll
- **Rollo/Nelko:** USB connection, standard print driver, 4x6" labels

Both work as standard OS printers — no special integration needed. Label CSS `@page` dimensions handle sizing.

## Security

- **Admin permissions:** Check-in configuration management (create/edit/delete configurations, windows, rooms, sessions) requires a new `@checkin_admin_required` decorator — accessible to Admin, Staff, and Volunteer Admin roles. Regular Volunteers cannot manage check-in settings. This decorator is added to `core/permissions.py` alongside the existing ones.
- **Kiosk views:** Public (no login required), gated by PIN. The kiosk is meant to be used by families, not staff — authentication happens via the kiosk PIN, not user accounts.
- **Checkout views:** Require `@login_required` — any authenticated user can process checkouts.
- **Kiosk PIN:** Required to enter kiosk mode. Stored in `OrganizationSettings.kiosk_pin`.
- **Security codes:** 4-character random alphanumeric, one per family per session. Used for pickup verification — parent presents pickup tag, volunteer matches code to checked-in children.
- **Custody flags:** Filled shield symbol on child's name tag alerts volunteers to check custody notes. Unauthorized pickup persons listed in the Person record.
- **No auto-lock:** Kiosk stays active until device screen timeout. Check-in window controls eligibility, not kiosk access.

## What Gets Deleted

- Entire `attendance/` app (models, views, urls, templates, forms, admin, migrations)
- `Room.min_age`, `Room.max_age`, `Room.min_grade`, `Room.max_grade` fields
- Existing Pillow-based `LabelGenerator` (replaced by CSS print approach)

## What Gets Kept

- `CheckIn` model (unchanged)
- `CheckInSession` model (modified with new FKs)
- `Room` model (simplified)
- `PrinterConfiguration` model (unchanged, for future server-side printing if needed)
- `LabelTemplate` model (unchanged)
- Security code generation logic
- Checkout flow (security code lookup → mark checked out)

## Backlog

- Automated follow-up workflow for new family profile completion
- Smart room auto-assignment by capacity
- Multiple concurrent kiosk support (multiple tablets, multiple configs)
- Server-side print support via print proxy (if browser printing proves insufficient)
