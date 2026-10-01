PROJECT CONTEXT — CHURCH OPERATIONS SYSTEM
==========================================

We are building a lightweight, modern church operations platform tailored for a small-to-mid-sized church (Bolivar Community Church). This is NOT a Rock RMS competitor and not an enterprise system. It is intentionally minimal, modular, and simple.

GOALS:
------
- Must be easy for non-technical staff to use.
- Must be portable and easy to deploy (Docker + Postgres).
- Must NOT depend on the original developer for day-to-day operation.
- Must avoid legacy complexity (no Lava, no plugin system, no monolithic abstractions).
- Must be maintainable by normal admins, not developers.
- Must run on an iPad for check-in.

TECH STACK:
-----------
- Backend: Django + Django REST Framework (DRF)
- Frontend: Django templates + HTMX (minimal JS)
- Database: PostgreSQL
- Deployment: Docker Compose + Traefik or Caddy
- Optional later: small local print server (FastAPI or Flask)

FOUNDATIONAL MODULES:
---------------------

1. AUTHENTICATION & PERMISSIONS
   - Users authenticated via email/password.
   - Roles: Admin, Staff (Volunteers later).
   - Basic Django permissions system.

2. PEOPLE & HOUSEHOLDS (CORE CRM)
   Tables:
   - Person
     - first_name, last_name
     - email, phone
     - birthdate
     - status (guest/regular/member/kid)
     - grade (optional)
     - notes (optional)
   - Household
     - name (e.g., "Smith Family")
     - address
     - phone
     - primary_adult
   - HouseholdMember (link table)
     - person_id
     - household_id
     - relationship_type (adult/child/etc.)

3. GROUPS
   - Group
     - name
     - description
     - type (small_group, volunteer_team, class, etc.)
   - GroupMember
     - group_id
     - person_id
     - role (leader/member)

4. EVENTS
   - Event
     - name
     - description
     - date/time(s)
     - allow_registration (bool)
     - registration_open, registration_close
     - capacity (optional)
     - allow_checkin (bool)
     - public_url_slug

5. EVENT REGISTRATIONS (PHASE 1)
   Must support:
   - Custom fields per event
   - Basic public registration page
   - Staff review/export

   Tables:
   - EventFormField
     - event_id
     - label
     - field_type (text, email, number, dropdown, checkbox)
     - required (bool)
     - order

   - Registration
     - event_id
     - person_id (nullable)
     - name
     - email
     - phone
     - timestamp

   - RegistrationAnswer
     - registration_id
     - field_id
     - value

   Public Flow:
   - Load event → load form fields → render full form → submit → validate → save.

6. ATTENDANCE / CHECK-IN (PHASE 1)
   Must support:
   - iPad-friendly UI
   - manual search OR barcode search
   - selecting child → marking check-in
   - no label printing needed for foundation (added later)

   Table:
   - AttendanceRecord
     - person_id
     - event_id
     - timestamp
     - method ("lookup", "barcode")

7. MESSAGING (PHASE 1)
   Very small scope:
   - Send email or SMS to person or group.
   - Integrations:
     - SMS → Twilio
     - Email → SendGrid/Postmark

   Table:
   - OutgoingMessage
     - message_type ("email" or "sms")
     - to_address
     - body
     - status ("sent", "failed")
     - timestamp

FRONTEND DESIGN:
----------------
- Staff portal uses Django templates + HTMX.
- Check-in uses a simple kiosk-like page with large input fields.
- Minimal JavaScript wherever possible.
- No SPA required for phase 1.
- Everything mobile/iPad-friendly.

NON-GOALS (NOT IN PHASE 1):
---------------------------
- Payment processing
- Volunteer drag-and-drop scheduling
- Complex conditional form logic
- Permissions beyond Admin/Staff
- Workflow engines
- Full contribution tracking
- Full check-in label printing (added later as a separate print server)

EXPECTED FILE STRUCTURE (SUGGESTED):
------------------------------------
project/
  manage.py
  config/
  app_core/
    models/
    views/
    urls.py
    templates/
  people/
  households/
  groups/
  events/
  registrations/
  attendance/
  messaging/
  templates/
  static/
docs/
  context.md  <-- this file
docker/
.env

SUMMARY:
---------
This system is a clean, modern, maintainable church admin tool with:
- People + Households
- Groups
- Events + Registrations
- Attendance + Check-in
- Basic Messaging

Backend = Django/DRF  
Frontend = HTMX  
Database = Postgres  
Deployment = Docker  
No bloat. No legacy. Just simple internal-tool style functionality.

END PROJECT CONTEXT
