# Graph Report - AnchorPoint  (2026-05-28)

## Corpus Check
- 143 files · ~97,702 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1543 nodes · 3175 edges · 66 communities detected
- Extraction: 65% EXTRACTED · 35% INFERRED · 0% AMBIGUOUS · INFERRED: 1099 edges (avg confidence: 0.56)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 100|Community 100]]
- [[_COMMUNITY_Community 103|Community 103]]
- [[_COMMUNITY_Community 105|Community 105]]
- [[_COMMUNITY_Community 106|Community 106]]
- [[_COMMUNITY_Community 124|Community 124]]
- [[_COMMUNITY_Community 132|Community 132]]
- [[_COMMUNITY_Community 134|Community 134]]

## God Nodes (most connected - your core abstractions)
1. `Person` - 89 edges
2. `Event` - 57 edges
3. `CheckInSession` - 51 edges
4. `Group` - 51 edges
5. `GroupMembership` - 47 edges
6. `Room` - 38 edges
7. `UserProfile` - 38 edges
8. `EventRegistration` - 37 edges
9. `PrinterConfiguration` - 36 edges
10. `OrganizationSettings` - 35 edges

## Surprising Connections (you probably didn't know these)
- `kiosk_unlock()` --calls--> `KioskPinForm`  [INFERRED]
  anchorpoint\checkin\views.py → anchorpoint\checkin\forms.py
- `IsStaffOrAdmin` --uses--> `UserProfile`  [INFERRED]
  anchorpoint\api\permissions.py → anchorpoint\core\models.py
- `IsAdminUserProfile` --uses--> `UserProfile`  [INFERRED]
  anchorpoint\api\permissions.py → anchorpoint\core\models.py
- `PersonSerializer` --uses--> `CheckInSession`  [INFERRED]
  anchorpoint\api\serializers.py → anchorpoint\checkin\models.py
- `PersonSerializer` --uses--> `Event`  [INFERRED]
  anchorpoint\api\serializers.py → anchorpoint\events\models.py

## Hyperedges (group relationships)
- **Attendance Configuration Management Views** — attendance_checkin_config_form, attendance_checkin_config_list [EXTRACTED 1.00]
- **Attendance App Kiosk Flow** — attendance_kiosk_unlock, attendance_kiosk_lookup, attendance_kiosk_family_select, attendance_kiosk_confirmation [INFERRED 0.90]
- **Check-In Admin Management Views** — checkin_dashboard, checkin_session_form, checkin_session_list, checkin_session_detail, checkin_room_form, checkin_room_list, checkin_printer_form, checkin_printer_list, checkin_checkout_lookup [INFERRED 0.95]
- **Checkin App Kiosk Flow** — checkin_kiosk_home, checkin_kiosk_lookup, checkin_kiosk_rooms, checkin_kiosk_complete [EXTRACTED 1.00]
- **Admin/User Management UI Templates** — user_form_html, user_list_html, manage_roles_html [INFERRED 0.95]
- **Event Management UI Templates** — event_form_html, event_list_manage_html, event_registrations_html, event_roster_html, registration_queue_html [INFERRED 0.95]
- **Public Event UI Templates** — event_list_public_html, event_detail_public_html, event_register_html [INFERRED 0.95]
- **People Module UI Templates** — people_list_html, people_detail_html, people_form_html [INFERRED 0.95]
- **AnchorPoint Core Tech Stack** — django_framework, django_rest_framework, htmx_frontend, postgresql_db, docker_compose_deployment, cloudflare_tunnel [EXTRACTED 1.00]
- **AnchorPoint Django Application Modules** — core_module, people_module, households_module, groups_module, events_module, checkin_module, messaging_module, registrations_module [EXTRACTED 1.00]
- **Check-In Kiosk Service Layer** — eligibility_service, session_manager_service, quick_registration_service, checkin_configuration_model, checkin_window_model [EXTRACTED 1.00]
- **Droplet Security Hardening Measures** — ufw_firewall, fail2ban, rationale_localhost_port_binding, github_actions_deploy [EXTRACTED 1.00]
- **System Email Types** — system_emails_feature, email_service_module, google_workspace_smtp [EXTRACTED 1.00]

## Communities (135 total, 41 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.04
Nodes (60): Command, OrganizationSettings, Exception, CommunicationLogAdmin, PhoneBlastAdmin, PhoneCallAdmin, SmsMessageAdmin, SmsRecipientAdmin (+52 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (59): OrganizationSettingsAdmin, UserProfileAdmin, organization_settings(), Render templates and send an email with HTML and plain-text alternatives.     C, Send a welcome email to a newly created user., Send a registration confirmation to the registrant., Notify all admin/staff users of a new event registration., _send() (+51 more)

### Community 2 - "Community 2"
Cohesion: 0.04
Nodes (74): CheckInAdmin, CheckInConfigurationAdmin, CheckInSessionAdmin, CheckInWindowAdmin, LabelTemplateAdmin, PrinterConfigurationAdmin, RoomAdmin, CheckInConfigurationForm (+66 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (51): IsAdminUserProfile, IsStaffOrAdmin, CheckInSessionSerializer, EventOccurrenceSerializer, EventSerializer, GroupMembershipSerializer, GroupSerializer, HouseholdMemberSerializer (+43 more)

### Community 4 - "Community 4"
Cohesion: 0.03
Nodes (75): DjangoSimpleTestCase, BrotherQLAdapter, Brother QL Adapter  Sends PIL images to a Brother QL label printer via the broth, Simple test-print image., Sends label images to a Brother QL printer.      connection_string:       - Netw, Convert PIL images to Brother QL raster and send to printer.         Cuts betwee, Check network reachability; USB is assumed available., Print a test label to verify printer health. (+67 more)

### Community 5 - "Community 5"
Cohesion: 0.02
Nodes (98): generate_security_code(), Generate a random security code for check-in., Generate a 4-character random alphanumeric security code., api_session_stats(), checkout_confirm(), checkout_lookup(), _config_form(), configuration_create() (+90 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (34): EventAdmin, EventOccurrenceInline, EventPhotoInline, EventRegistrationAdmin, EventRegistrationAttendeeInline, ReleaseDocumentAdmin, EventForm, EventOccurrenceForm (+26 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (33): AttendanceRecordAdmin, CheckInConfigurationAdmin, CheckInWindowAdmin, CheckInWindowInline, CheckInConfigurationForm, CheckInSelectionForm, CheckInWindowForm, KioskLookupForm (+25 more)

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (70): Check-In Configuration Form Template, Check-In Configuration List Template, Attendance Kiosk Confirmation Template, Attendance Kiosk Family Select Template, Attendance Kiosk Lookup Template, Attendance Kiosk Unlock (PIN) Template, Attendee-to-Person Matching Queue Concept, Attendee Model (+62 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (48): AnchorPoint TODO List, Attendance Module (Legacy, Deprecated), BolivarSocialAccountAdapter (Custom OAuth Adapter), @checkin_admin_required Permission Decorator, CheckInConfiguration Model (Schedule + Eligibility + Rooms), Check-In Kiosk System (Tablet + Thermal Printer), CheckIn Module (Kiosk Check-In System), Check-In System Plan Document (+40 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (23): Meta, PersonForm, age(), formatted_address(), is_minor(), normalize_phone(), Strip all non-digit characters from a phone number., PeopleDetailCommunicationTests (+15 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (20): ABC, BasePrinterAdapter, BasePrinterAdapter, is_available(), print_image(), Base Printer Adapter  Abstract base class for all printer adapters., Base class for printer adapters., Initialize the printer adapter.          Args:             connection_string: (+12 more)

### Community 12 - "Community 12"
Cohesion: 0.16
Nodes (25): _apply_contact_data(), create_person_from_attendee(), enroll_person_in_event_group(), ensure_event_group(), _ensure_household(), _ensure_person(), link_guardian_household(), manually_assign_attendee() (+17 more)

### Community 13 - "Community 13"
Cohesion: 0.1
Nodes (23): admin_required(), checkin_admin_required(), communications_required(), _get_user_profile(), has_communications_access(), is_admin(), is_checkin_admin(), is_staff_or_above() (+15 more)

### Community 14 - "Community 14"
Cohesion: 0.07
Nodes (11): ApiConfig, AppConfig, AttendanceConfig, CheckinConfig, CoreConfig, EventsConfig, GroupsConfig, HouseholdsConfig (+3 more)

### Community 15 - "Community 15"
Cohesion: 0.11
Nodes (24): AnchorPoint CLAUDE.md Developer Guide, Project Context Document, AnchorPoint Deployment Guide, AnchorPoint Church Management System, Cloudflare Tunnel, Django 5.2 Framework, Django REST Framework, Docker Compose Deployment (+16 more)

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (5): _grade_index(), is_person_eligible(), Return numeric index for grade comparison, or -1 if unknown., Check if a person is eligible for a check-in configuration.      All filters a, EligibilityTests

### Community 17 - "Community 17"
Cohesion: 0.18
Nodes (18): Base HTML Template, Kiosk PIN Security, OrganizationSettings Model, PhoneBlast Model, ReleaseDocument Model, Release Document Library, SMS Blackout Window, SmsMessage Model (+10 more)

### Community 19 - "Community 19"
Cohesion: 0.29
Nodes (11): Event Model, Jingle Jam Christmas Celebration Event, Registration Model, Jingle Jam Christmas Event Photo, Email Base Template, Registration Confirmation Email (HTML), Registration Confirmation Email (Text), Staff New Registration Notification (HTML) (+3 more)

### Community 20 - "Community 20"
Cohesion: 0.29
Nodes (3): Create Person + Household records for a new family at the kiosk.      Returns, register_new_family(), QuickRegistrationTests

### Community 21 - "Community 21"
Cohesion: 0.31
Nodes (5): BaseCommand, Command, generate_password(), Management command to create beta test users for AnchorPoint.  Usage:     pyt, Generate a secure random password.

### Community 22 - "Community 22"
Cohesion: 0.33
Nodes (7): Migration, normalize_phone(), populate_normalized_phone(), Backfill normalized_phone for all existing Person records., Clear normalized_phone (reverse migration)., Strip all non-digit characters from a phone number., reverse_populate()

### Community 23 - "Community 23"
Cohesion: 0.33
Nodes (3): ApiMeView, ApiRootView, APIView

### Community 24 - "Community 24"
Cohesion: 0.4
Nodes (4): health_check(), URL configuration for anchorpoint project.  The `urlpatterns` list routes URLs, Simple health check endpoint for Docker/load balancer., Simple health check endpoint for Docker/load balancer.

### Community 26 - "Community 26"
Cohesion: 0.5
Nodes (3): drop_attendance_tables(), Migration, Drop old attendance tables if they exist (works on both PG and SQLite).

## Knowledge Gaps
- **268 isolated node(s):** `Run administrative tasks.`, `Simple health check endpoint for Docker/load balancer.`, `Dynamic form for selecting family members and rooms at check-in.`, `Return list of (person_id, room_id) for selected members.`, `Generate a 4-character random alphanumeric security code.` (+263 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **41 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Person` connect `Community 3` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 6`, `Community 7`, `Community 10`, `Community 13`, `Community 16`, `Community 20`?**
  _High betweenness centrality (0.234) - this node is a cross-community bridge._
- **Why does `CheckInSession` connect `Community 2` to `Community 3`, `Community 4`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `Group` connect `Community 3` to `Community 16`, `Community 0`, `Community 7`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 85 inferred relationships involving `Person` (e.g. with `PersonSerializer` and `Meta`) actually correct?**
  _`Person` has 85 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `Event` (e.g. with `PersonSerializer` and `Meta`) actually correct?**
  _`Event` has 48 INFERRED edges - model-reasoned connections that need verification._
- **Are the 44 inferred relationships involving `CheckInSession` (e.g. with `PersonSerializer` and `Meta`) actually correct?**
  _`CheckInSession` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `Group` (e.g. with `PersonSerializer` and `Meta`) actually correct?**
  _`Group` has 48 INFERRED edges - model-reasoned connections that need verification._