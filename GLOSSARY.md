# Glossary

Domain terms used in AnchorPoint's code, docs and issues. Use these words; avoid the listed synonyms.

## Outbound communications (`messaging/`)

**Communication**: one thing sent to one person or many: a text, a phone blast, or (later) an email.
Stored as a `Communication` row. _Avoid_: message (too vague), blast (only the voice kind).

**Delivery**: one recipient's copy of a Communication, with its own status: pending, sent, answered,
no answer, failed, or skipped (with a reason such as opted out). The Delivery is the audit trail: a
person's communication history is their Deliveries. _Avoid_: recipient row, log entry.

**Channel**: how a Communication travels: `sms`, `voice`, or `email`. Each channel has one adapter
that does the actual sending (Twilio for sms/voice; an in-memory fake in tests).

**Broadcast**: a Communication a staff member writes and sends to a person or a group. Broadcasts
obey opt-in and the blackout window, and always go out through the every-minute scheduler.

**Transactional**: a Communication triggered by an event, not written by staff, e.g. the check-in
pickup-code text. Obeys opt-in, ignores the blackout window, sends immediately.

**Blackout window**: the organization's configured quiet hours (Settings → Organization). Broadcasts
that come due inside it wait until it ends.

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
