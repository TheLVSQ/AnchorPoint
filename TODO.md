# AnchorPoint TODO

The one backlog for the project. `CLAUDE.md` is reference only; open work goes here.

## Top priority

- [ ] **UI refresh.** Modernize the look without making it busier. Sweep every page for consistency.
- [ ] **Security review.** Do a full pass before making the repo public. Cover auth and role gates, IDOR on every `<id>` URL, kiosk/agent endpoints, file uploads, secrets in history, dependency versions.

## Next up

- [ ] **Nightly family/person hygiene job + admin review page.** Run at 2–3am via the cron sidecar.
  - Detect orphaned households (0 members, or no adults).
  - Detect likely duplicate people and households (same normalized phone, address, or last name).
  - Write the findings to a review queue. Add an **admin-only page** that lists them, with merge, edit, delete and dismiss actions.
  - The merge service already exists (#59). It re-points HouseholdMembers, check-ins and event registrations.
- [ ] **Address verification on person add.** Compare USPS Web Tools API (free, US-only) with Smarty/Lob (paid, easier).
  - Pattern: normalize, autocomplete on blur, store a `verified` flag.
  - Degrade gracefully when no API is configured.
- [ ] **Email sending.** Transactional plus blast, alongside the existing SMS/phone blasts.
  - Log every send to `CommunicationLog`.
  - Respect opt-in and blackout rules.
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
