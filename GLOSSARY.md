# Glossary

Domain terms used in AnchorPoint's code, docs and issues. Use these words; avoid the listed synonyms.

## Outbound communications (`messaging/`)

**Communication**: one thing sent to one person or many: a text, a phone blast, or an email.
Stored as a `Communication` row. _Avoid_: message (too vague), blast (only the voice kind).

**Delivery**: one recipient's copy of a Communication, with its own status: pending, sent, answered,
no answer, failed, or skipped (with a reason such as opted out). The Delivery is the audit trail: a
person's communication history is their Deliveries. _Avoid_: recipient row, log entry.

**Channel**: how a Communication travels: `sms`, `voice`, or `email`. Each channel has one adapter
that does the actual sending (Twilio for sms/voice, Django's mail backend for email; an in-memory
fake in tests).

**Broadcast**: a Communication a staff member writes and sends to a person or a group: a text or a
phone blast (email is system-only, so staff can't write one). Broadcasts obey opt-in and the
blackout window, and always go out through the every-minute scheduler.

**Transactional**: a Communication triggered by an event, not written by staff, e.g. the check-in
pickup-code text. Obeys opt-in, ignores the blackout window, sends immediately.

**Blackout window**: the organization's configured quiet hours (Settings → Organization). Text and
phone-blast broadcasts that come due inside it wait until it ends. Email ignores it.

**Opt-in**: a person's consent for a channel. `phone_opt_in` (texts + phone blasts) is off until staff
tick it. `email_opt_in` is on by default and turns off when the person clicks **Unsubscribe** in any
email sent through the email channel (a signed, non-expiring link).

**Outbound communications module**: `messaging/outbound.py`, the one place that decides who may be
contacted, when, over which channel, and records what happened.

## Check-in (`checkin/`)

**Check-in**: one person's record at one check-in session (`CheckIn`). It is always in exactly one
**state**, derived from `arrived_at` / `checked_out_at` / `no_show` (never stored):

- **Expected**: pre-staged on the Pre-print page; label printed ahead, not here yet.
- **No-show**: was expected, confirmed absent. Reversible: if they turn up, they become Present.
- **Present**: arrived and not checked out. "Here now", room occupancy, and who can be checked out.
- **Checked out**: picked up.

**Active**: not checked out (Expected, No-show or Present). Holds a live pickup code; a person has
at most one active check-in per session. _Avoid_: "open", "current".

**Attended**: arrived at some point (Present or Checked out). What attendance counts.
_Avoid_: "checked in" for this (it's ambiguous with the act of checking in).

Every state question and state change goes through `CheckIn` (`checkin/models.py`):
`session.checkins.expected()/no_show()/present()/checked_out()/active()/attended()`,
`.state_counts()`, and the transitions `arrive()`, `mark_no_show()`, `check_out()`.

**Pickup code**: the 4-character code on a check-in's label and on the family's pickup tag; checkout
matches on it. Unique among active check-ins in a session. A family usually holds one, but can hold
two (see Walk-in), and then gets one pickup tag per code. _Avoid_: security code (the field name).

**Pre-staged**: a check-in created ahead of time on the Pre-print page (starts Expected). Pre-print is
staff-only, so it reuses the family's active pickup code to keep one code per family.

**Walk-in**: a check-in made at the kiosk without pre-staging (created Present). Each kiosk submission
mints a FRESH pickup code shared by the walk-in siblings in it, never the family's existing code: the
kiosk is self-service, so it must not print or show a live code to whoever is standing there.

Checking a family in, staging families and printing labels all go through
`checkin/services/family_checkin.py`: `check_in_family()`, `stage_families()`,
`confirm_arrivals()`, `print_labels()`.

## People (`people/`)

**Match**: deciding an incoming record (a registration attendee, an import row, a kiosk add-child)
is a Person we already have. Automatic matches need the first name to agree plus one of: external
id, email, birthdate, phone, or membership of the given family. Ambiguous = no match. Every intake
path uses `people/services/identity.py`. _Avoid_: "dedupe" for this (that's merging two existing
records).

**Absorb**: applying a matched record's data to the existing Person: fill blank fields, add safety
text (allergies, custody, pickup restrictions, notes), never overwrite or drop. Merging two people
absorbs one into the other.

## Families (`households/`)

**Family**: a `Household`: people who live and check in together. New families are named
"{Surname} Family". _Avoid_: "household" in UI text (it's the model name).

**Role**: a member's relationship in a family: Adult, Child, Student or Other. Always given
explicitly; adults get pickup-code texts and are listed as guardians.

**Primary adult**: the family's main adult, always an Adult member, or blank. When the primary leaves
or stops being an adult, the longest-standing other adult takes over; a family with no primary gets
its first adult. Every membership change goes through `households/membership.py`.

## Logins (`core/`)

**Team Member**: the login role for scheduled volunteers (worship, greeters, BKiDS…). Sees their own
dashboard, profile and help, never check-in or anyone else's data. Invites create Team Members.
_Avoid_: calling them "Volunteers": the **Volunteer** role means the check-in team, which can see and
check out children.

**Invite**: a staff action on a person's profile that gives them a login and emails a single-use
set-your-password link. Resend until they've signed in once; after that they use "Forgot password?".

## Teams & Plans (`scheduling/`, `groups/`)

**Team**: a Group people are scheduled from (worship, kids, greeters…). Check-in classrooms and
event-registration groups are never teams. _Avoid_: ministry, department.

**Position**: a role on a team that someone is scheduled into (Keys, Vocals, Sound). Each team member
is marked with the positions they can fill. _Avoid_: slot, role (role means member/leader).

**Serving weeks**: which weeks of the month a person serves on one team ("3rd only"). A standing
pattern, set per team; the week is the date's week of the month. _Avoid_: calling it a blockout.

**Blockout**: dates a person can't serve on any team (vacation, "out the 14th"), optionally repeating
every year. Exceptions only; regular patterns are serving weeks.

**Service type**: a kind of service that gets scheduled ("Sunday Morning", "VBS 2027"): its weekday
(or every day, for VBS), time, and how many of each position each date needs. _Avoid_: event (that's
the Events app).

**Plan**: one date of a service type, holding who serves in each position. One plan covers every
team on that date. _Avoid_: service, schedule (the schedule is the grid of plans).

**Assignment**: one person in one position on one plan: Pending, Accepted or Declined. Declined ones
stay visible but don't fill the position.

**Already serving**: the person has another (not declined) assignment that date, on any plan or
position. A warning, like being outside their serving weeks or blocked out; staff can still schedule.
