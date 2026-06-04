# Group Management — Design Spec

## Overview

Add a group detail page with inline member management to the groups module. Currently, group names in the list are plain text with no link; there is no way to view, edit, or manage members of a group. This spec adds full CRUD for groups and HTMX-powered member search/add/remove on the detail page.

No model changes required. `Group` and `GroupMembership` already have all necessary fields.

## URLs

```
/groups/<pk>/                         → group_detail         (member list + metadata)
/groups/<pk>/edit/                    → group_edit           (edit group fields)
/groups/<pk>/delete/                  → group_delete         (confirm + delete)
/groups/<pk>/members/add/             → group_member_add     (HTMX POST: add person or household)
/groups/<pk>/members/<mid>/remove/    → group_member_remove  (HTMX POST: remove one member)
/groups/<pk>/member-search/           → group_member_search  (HTMX GET: name search dropdown)
```

## Detail Page

**Template:** `groups/templates/groups/group_detail.html`

- Header: group name, category chip, active/archived chip, Edit and Delete buttons
- Info row: location, meeting schedule, capacity (only rendered if set)
- Member list wrapped in `<div id="member-list">` — each row shows person's full name (linked to their profile), role chip (Member/Leader), and a Remove button
- Empty state message when no members
- Add member section below the list: text input with `hx-get="{% url 'groups:member_search' group.pk %}"`, `hx-trigger="keyup changed delay:300ms"`, `hx-target="#member-search-results"`. Results appear in `<div id="member-search-results">` directly below the input.

## Member Search Partial

**URL:** `GET /groups/<pk>/member-search/?q=<query>`  
**Template:** `groups/templates/groups/group_member_search_results.html`  
**Permission:** `@staff_required`

- Returns an HTML partial (no base template extends)
- Queries `Person` where first or last name contains `q` (case-insensitive), limit 10
- Excludes people already in the group
- Each result row: full name + "Add" button (posts `person_id`)
- If person belongs to a household and that household has members not yet in the group, also shows "Add family (N people)" button (posts `household_id`)
- Empty `q` → returns empty string (collapses dropdown)

## Add Member

**URL:** `POST /groups/<pk>/members/add/`  
**Permission:** `@staff_required`

Accepts either:
- `person_id=<id>` — creates one `GroupMembership(group, person, role="member")`, silently ignores if already a member (`get_or_create`)
- `household_id=<id>` — bulk-creates memberships for all `Person` records in that household not already in the group

Returns the re-rendered `group_member_list.html` partial targeting `#member-list` via `hx-swap="outerHTML"`.

## Remove Member

**URL:** `POST /groups/<pk>/members/<mid>/remove/`  
**Permission:** `@staff_required`

- Looks up `GroupMembership` by `pk=mid` — 404 if not found or if `membership.group_id != pk` (prevents cross-group removal)
- Deletes the membership
- Returns the re-rendered `group_member_list.html` partial targeting `#member-list`

## Member List Partial

**Template:** `groups/templates/groups/group_member_list.html`

Renders `<div id="member-list">` containing the full current member list. Used on initial page load (via `{% include %}`) and returned by both add and remove endpoints. Shared render logic via a `_render_member_list(request, group)` helper in `views.py`.

## Edit Group

**URL:** `GET/POST /groups/<pk>/edit/`  
**Template:** `groups/templates/groups/group_form.html` (reused, title changes to "Edit Group")  
**Permission:** `@staff_required`

- Reuses `GroupForm` with `instance=group`
- On success: redirect to `groups:detail`
- Cancel button links to `groups:detail` (the form template receives a `cancel_url` context variable)

## Delete Group

**URL:** `GET/POST /groups/<pk>/delete/`  
**Template:** `groups/templates/groups/group_confirm_delete.html`  
**Permission:** `@staff_required`

- GET: confirmation page showing group name and member count
- POST: deletes group (cascade removes all `GroupMembership` records), redirects to `groups:list`

## List Page Changes

`group_list.html`: wrap each group name in `<a href="{% url 'groups:detail' group.pk %}">` with the `ghost-link` class. Add a "View →" link on the right side of each list item for clarity.

## Files Changed

| File | Change |
|------|--------|
| `groups/views.py` | Add `group_detail`, `group_edit`, `group_delete`, `group_member_add`, `group_member_remove`, `group_member_search`, `_render_member_list` helper |
| `groups/urls.py` | Add 6 URL patterns |
| `groups/templates/groups/group_list.html` | Make group names clickable links |
| `groups/templates/groups/group_form.html` | Accept `cancel_url` context var for the Cancel button |
| `groups/templates/groups/group_detail.html` | New |
| `groups/templates/groups/group_member_list.html` | New HTMX partial |
| `groups/templates/groups/group_member_search_results.html` | New HTMX partial |
| `groups/templates/groups/group_confirm_delete.html` | New |

No migrations required.

## Security

- All views use `@staff_required`
- Remove endpoint validates `membership.group_id == pk` to prevent cross-group manipulation
- Add endpoint uses `get_or_create` — idempotent, no duplicate memberships
- HTMX endpoints return partials only; no sensitive data exposed beyond what the full page already shows

## Testing

- `group_detail` returns 200 and shows group name
- `group_edit` updates fields and redirects to detail
- `group_delete` removes group and all memberships, redirects to list
- `group_member_search` excludes existing members, returns up to 10 results
- `group_member_add` with `person_id` creates membership, re-renders list
- `group_member_add` with `household_id` creates memberships for all non-members in household
- `group_member_remove` deletes membership, returns 404 for wrong group
- List page: group names link to detail page
