# AnchorPoint API

This document describes the current Django REST Framework (DRF) API surface in AnchorPoint.

## Base URLs

- API base: `/api/v1/`
- Schema: `/api/schema/`
- HTML docs: `/api/docs/`

## Authentication

- Default auth is Django session authentication.
- Most endpoints require an authenticated user.
- Permission checks use role logic from `UserProfile`:
  - Staff-level access: `admin`, `staff`, `volunteer_admin`
  - Some endpoints are public read-only (events list/detail).

## Response Conventions

- Paginated list endpoints use page-number pagination:
  - Default `page_size=25`
  - Query params: `page`, `page_size` (max 100)
- Search and ordering are enabled where configured:
  - Search: `?search=...`
  - Ordering: `?ordering=field` or `?ordering=-field`
- API errors are wrapped by a custom exception handler:
  - Shape: `{"error": {"code": <status>, "details": ...}}`

## Endpoints

### Root + Profile

- `GET /api/v1/`
  - Returns API name/version metadata.
- `GET /api/v1/me/`
  - Returns current authenticated user profile summary.

### People

- `GET /api/v1/people/`
- `POST /api/v1/people/`
- `GET /api/v1/people/{id}/`
- `PUT /api/v1/people/{id}/`
- `PATCH /api/v1/people/{id}/`
- `DELETE /api/v1/people/{id}/`

Notes:
- Staff-level access required.
- Supports `?search=` across name/email/phone fields.
- Supports ordering by name/status/birthdate.
- Optional status filter: `?status=member` (or other valid status values).

### Households

- `GET /api/v1/households/`
- `POST /api/v1/households/`
- `GET /api/v1/households/{id}/`
- `PUT /api/v1/households/{id}/`
- `PATCH /api/v1/households/{id}/`
- `DELETE /api/v1/households/{id}/`

Custom actions:
- `GET /api/v1/households/{id}/members/`
- `POST /api/v1/households/{id}/add_member/`
  - Body: `{"person": <person_id>, "relationship_type": "adult|child|student|other"}`
- `POST /api/v1/households/{id}/remove_member/`
  - Body: `{"person": <person_id>}`

Notes:
- Staff-level access required.

### Groups

- `GET /api/v1/groups/`
- `POST /api/v1/groups/`
- `GET /api/v1/groups/{id}/`
- `PUT /api/v1/groups/{id}/`
- `PATCH /api/v1/groups/{id}/`
- `DELETE /api/v1/groups/{id}/`

Custom actions:
- `GET /api/v1/groups/{id}/members/`
- `POST /api/v1/groups/{id}/add_member/`
  - Body: `{"person": <person_id>, "role": "member|leader", "notes": ""}`
- `POST /api/v1/groups/{id}/remove_member/`
  - Body: `{"person": <person_id>}`

Notes:
- Staff-level access required.

### Events

- `GET /api/v1/events/`
- `GET /api/v1/events/{id}/`
- `POST /api/v1/events/`
- `PUT /api/v1/events/{id}/`
- `PATCH /api/v1/events/{id}/`
- `DELETE /api/v1/events/{id}/`

Notes:
- Unauthenticated users can list/retrieve published events only.
- Staff-level users can create/update/delete and view unpublished events.

### Check-In Sessions

- `GET /api/v1/checkin/sessions/`
- `GET /api/v1/checkin/sessions/{id}/`
- `GET /api/v1/checkin/sessions/{id}/stats/`

Notes:
- Requires authentication.
- `stats` returns `checked_in`, `checked_out`, `total`, and per-room counts.

## Current Scope

This API layer is actively being expanded. Current endpoints focus on:

- People
- Households + memberships
- Groups + memberships
- Events
- Check-in session read/stats

Future phases can add event registration create/update flows, messaging APIs, and broader public API capabilities.
