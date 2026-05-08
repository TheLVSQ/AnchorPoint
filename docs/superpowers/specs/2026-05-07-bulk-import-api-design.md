# Bulk Import API — Design Spec

## Overview

A REST API for bulk-importing People and Households into AnchorPoint. Designed for use from Python scripts in the short-term and as the foundation for an admin UI bulk-import feature later.

Uses Django REST Framework (already in `requirements.txt`) with Token authentication. A single bulk endpoint handles both People creation and Household grouping via a client-assigned `household_ref` field.

## Authentication

**Type:** DRF `TokenAuthentication`

- `rest_framework.authtoken` added to `INSTALLED_APPS` — provides the `Token` model
- Admin generates a token once at `/admin/authtoken/token/`
- Scripts include it as: `Authorization: Token <key>`
- Custom permission class (`IsAdminProfile`) verifies the token owner has `profile.role == "admin"`

**DRF settings in `settings.py`:**
```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}
```

## Endpoint

### `POST /api/v1/people/bulk/`

Accepts a JSON array of person objects. Upserts each person, then groups by `household_ref` to create/update Households and link members.

**Permission:** Token required + `IsAdminProfile`

**Request body:** JSON array of person objects (see fields below).

**Example:**
```json
[
  {
    "first_name": "John",
    "last_name": "Smith",
    "email": "john@example.com",
    "phone": "+15551234567",
    "phone_opt_in": true,
    "household_ref": "smith-001",
    "household_name": "Smith Family"
  },
  {
    "first_name": "Jane",
    "last_name": "Smith",
    "email": "jane@example.com",
    "household_ref": "smith-001"
  },
  {
    "first_name": "Dave",
    "last_name": "Jones",
    "email": "dave@example.com"
  }
]
```

**Response (HTTP 200):**
```json
{
  "created": 2,
  "updated": 1,
  "households_created": 1,
  "households_updated": 0,
  "errors": []
}
```

**Partial errors (HTTP 200):**
Valid records are saved; invalid records are reported without blocking the rest:
```json
{
  "created": 2,
  "updated": 0,
  "households_created": 1,
  "households_updated": 0,
  "errors": [
    {"index": 2, "errors": {"first_name": ["This field is required."]}}
  ]
}
```

**Malformed body (HTTP 400):** Returned only when the entire request body is not a valid JSON array.

## Person Fields

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `first_name` | ✅ | string | max 150 chars |
| `last_name` | ✅ | string | max 150 chars |
| `email` | — | string | Primary upsert key. Case-insensitive match. |
| `phone` | — | string | Fallback upsert key if no email match. Normalized before matching. |
| `gender` | — | string | `male`, `female`, `other`, `unknown` |
| `birthdate` | — | string | `YYYY-MM-DD` |
| `marital_status` | — | string | `single`, `married`, `engaged`, `separated`, `divorced`, `widowed` |
| `grade` | — | string | `pre-k`, `k`, `1`–`12` |
| `status` | — | string | Free text, defaults to `guest` |
| `phone_opt_in` | — | boolean | Defaults to `true` (matches Person model default) |
| `address_line1` | — | string | |
| `address_line2` | — | string | |
| `city` | — | string | |
| `state` | — | string | |
| `postal_code` | — | string | |
| `notes` | — | string | |
| `household_ref` | — | string | Temporary grouping key — not stored in DB |
| `household_name` | — | string | Only used with `household_ref`. Defaults to `"{last_name} Family"` from first member. |

## Upsert Logic

1. **Email match** (`email__iexact`) — if a Person with this email exists, update it
2. **Phone match** (normalize both, compare `normalized_phone`) — if email not provided or no email match
3. **No match** — create new Person

On update, only fields present in the payload are updated (partial update). Fields absent from the payload are left unchanged.

## Household Logic

After all people are upserted:

1. Collect all `household_ref` values from the payload
2. For each unique `household_ref`:
   - Collect all `Person` records from that group
   - Look up Household by `household_name` (case-insensitive) — if found, use it; otherwise create new
   - `household_name` defaults to `"{first_member.last_name} Family"` if not specified in payload
   - Add all group members to the household via `HouseholdMember` (skip if already a member)

## Error Handling

- Per-item errors are collected and returned in the `errors` array with the item's `index` (0-based)
- Invalid items are skipped; valid items are processed normally
- If `household_ref` members include invalid items, those invalid items are excluded from the household but valid members are still linked
- HTTP 400 only for completely malformed requests (not a JSON array, missing `Content-Type: application/json`)

## Python Script Usage

```python
import requests

TOKEN = "your-token-here"
BASE_URL = "https://anchorpoint.bolivar.church"

people = [
    {"first_name": "John", "last_name": "Smith", "email": "john@bolivar.church", "household_ref": "h1"},
    {"first_name": "Jane", "last_name": "Smith", "email": "jane@bolivar.church", "household_ref": "h1"},
]

response = requests.post(
    f"{BASE_URL}/api/v1/people/bulk/",
    json=people,
    headers={"Authorization": f"Token {TOKEN}"},
)
print(response.json())
```

## Files Changed

| File | Change |
|------|--------|
| `anchorpoint/settings.py` | Add `rest_framework`, `rest_framework.authtoken` to INSTALLED_APPS; add `REST_FRAMEWORK` config |
| `anchorpoint/anchorpoint/urls.py` | Add `api/v1/` URL prefix |
| `anchorpoint/api/__init__.py` | New app |
| `anchorpoint/api/apps.py` | App config |
| `anchorpoint/api/permissions.py` | `IsAdminProfile` permission class |
| `anchorpoint/api/serializers.py` | `PersonBulkSerializer` |
| `anchorpoint/api/views.py` | `PeopleBulkView` |
| `anchorpoint/api/urls.py` | URL patterns |
| `anchorpoint/api/tests.py` | Tests |

One new migration required (`authtoken` tables from DRF).

## Testing

- Unauthenticated request → 401
- Non-admin token → 403
- Valid array → correct created/updated counts
- Email upsert: existing person updated, not duplicated
- Phone upsert fallback: matched and updated
- `household_ref` grouping: household created, members linked
- Partial errors: valid items saved, error items reported in response
- Malformed body → 400
- Empty array → 200 with all zeros
