# AnchorPoint TODO

The one backlog for the project. `CLAUDE.md` is reference only; open work goes here.

## Top priority

_(empty — the UI refresh and security review both shipped 2026-10-01; see Completed.)_

## Next up

- [ ] **Teams & Plans: replace Planning Center** (#134). Phases 1–2 live before the Jan 1, 2027 renewal.
  - [ ] Per-plan needs (e.g. an extra vocalist on Easter): today a plan always uses its service type's needs.
  - [ ] Removing someone from a date (or deleting the date) after their request went out doesn't tell them.
  - [ ] Schedule requests are email only: a "text me instead" option for people with no email.
- [ ] **Address verification on person add.** Compare USPS Web Tools API (free, US-only) with Smarty/Lob (paid, easier).
  - Pattern: normalize, autocomplete on blur, store a `verified` flag.
  - Degrade gracefully when no API is configured.
- [ ] **Bulk import API.** The spec is at `docs/superpowers/specs/2026-05-07-bulk-import-api-design.md`. Reuse the `import_signups` matching logic.
- [ ] **REST API.** Rebuild it on main. The May attempt (people, households, groups, events, check-in session endpoints in `anchorpoint/api/`) diverged too far to merge. It's preserved as the tag `archive/development`; view it with `git show archive/development:anchorpoint/api/viewsets.py`. DRF is already pinned in `docker/requirements.txt` but isn't in `INSTALLED_APPS`.

## Backlog

### Features
- [ ] Embed code generator for event info
- [ ] Check-in: Create Room flow → age/grade auto-assignment
  - Min/Max as a K-12 dropdown
  - Make the "Active" checkbox sit next to the word "Active" and hard to miss
- [ ] User permissions page: something better than an all-users view
- [ ] Add Person form: phone number input formatting
- [ ] Add Person form: email format validation

### Tech debt
- [ ] `select_related`/`prefetch_related` on dashboard queries
- [ ] Refactor fat views into service layers (people, households, groups)
- [ ] Indexes on `Event.slug` and `Event.registration_token` (`Person.email` is done)
- [ ] Pagination on the remaining long lists (people and groups are done)
- [ ] SMS delivery-status webhooks (only phone calls track status today)

## Completed

- [x] Add Gender to people records
- [x] Add indicator for adults vs minors
- [x] Google SSO (bolivar.church domain only)
- [x] Pagination on people and groups lists
- [x] Database indexes (Person.email, checkin N+1 fixes)
- [x] Messaging service tests
- [x] Extract duplicate recipient query logic
- [x] Phone blast stats and live progress
- [x] Group detail, edit, delete, member management
- [x] User creation flow — email as login, Person linking
- [x] Live people search (HTMX)
- [x] Mobile nav scroll fix
- [x] Media files served in production
- [x] Org logo display fix
- [x] Favicon; group status dropdown; person status dropdown; single save on permissions page
- [x] Family management UI (/families/), people tile view, "join existing family" fix
- [x] Person/Household merge service (#59)
- [x] Check-in: pre-print, kiosk PIN gate, offline-agent fallback, Brother QL direct-USB backend
- [x] Reports: group roster, session attendance, birthday/VBS postcards, missing data
- [x] Local dev/test environment (`scripts/dev-setup.sh`)
- [x] Security review (Oct 2026): 5 fix batches — kiosk/checkout safety, Volunteer Admin scope, checkout toggle, public-input hardening, family-safety flags + alerts, auth/media gating, login throttling, dependency patches
- [x] Maintenance: daily health email, host status cron, Tuesday security reboot, Docker prune, Dependabot
- [x] UI refresh ("Harbor" design system, Figtree, dark mode, sidebar, every staff page redesigned; kiosk unchanged)
- [x] Events: per-event "require birthdate + grade for each attendee" (kids' events)
- [x] Nightly family/person hygiene job + admin Data cleanup page (merge/delete/dismiss)
