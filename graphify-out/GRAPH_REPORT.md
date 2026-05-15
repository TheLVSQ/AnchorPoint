# Graph Report - AnchorPoint  (2026-05-14)

## Corpus Check
- 134 files · ~94,776 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1465 nodes · 2941 edges · 61 communities detected
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 945 edges (avg confidence: 0.57)
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
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 96|Community 96]]
- [[_COMMUNITY_Community 98|Community 98]]
- [[_COMMUNITY_Community 99|Community 99]]
- [[_COMMUNITY_Community 117|Community 117]]
- [[_COMMUNITY_Community 125|Community 125]]
- [[_COMMUNITY_Community 127|Community 127]]

## God Nodes (most connected - your core abstractions)
1. `Person` - 75 edges
2. `Event` - 43 edges
3. `Room` - 37 edges
4. `EventRegistration` - 37 edges
5. `Group` - 37 edges
6. `CheckInSession` - 36 edges
7. `UserProfile` - 36 edges
8. `PrinterConfiguration` - 35 edges
9. `OrganizationSettings` - 35 edges
10. `Base Template (base.html)` - 35 edges

## Surprising Connections (you probably didn't know these)
- `CheckInConfigurationAdmin` --uses--> `PrinterConfiguration`  [INFERRED]
  anchorpoint\checkin\admin.py → anchorpoint\checkin\models.py
- `CheckInWindowAdmin` --uses--> `PrinterConfiguration`  [INFERRED]
  anchorpoint\checkin\admin.py → anchorpoint\checkin\models.py
- `RoomAdmin` --uses--> `PrinterConfiguration`  [INFERRED]
  anchorpoint\checkin\admin.py → anchorpoint\checkin\models.py
- `CheckInSessionAdmin` --uses--> `PrinterConfiguration`  [INFERRED]
  anchorpoint\checkin\admin.py → anchorpoint\checkin\models.py
- `CheckInAdmin` --uses--> `PrinterConfiguration`  [INFERRED]
  anchorpoint\checkin\admin.py → anchorpoint\checkin\models.py

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

## Communities (128 total, 40 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (148): CheckInAdmin, CheckInConfigurationAdmin, CheckInSessionAdmin, CheckInWindowAdmin, LabelTemplateAdmin, PrinterConfigurationAdmin, RoomAdmin, CheckInConfigurationForm (+140 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (60): Command, OrganizationSettings, Exception, CommunicationLogAdmin, PhoneBlastAdmin, PhoneCallAdmin, SmsMessageAdmin, SmsRecipientAdmin (+52 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (59): OrganizationSettingsAdmin, UserProfileAdmin, organization_settings(), Render templates and send an email with HTML and plain-text alternatives.     C, Send a welcome email to a newly created user., Send a registration confirmation to the registrant., Notify all admin/staff users of a new event registration., _send() (+51 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (78): PrinterConfiguration, Printer setup for label printing., Printer settings for label printing., DjangoSimpleTestCase, BrotherQLAdapter, Brother QL Adapter  Sends PIL images to a Brother QL label printer via the broth, Simple test-print image., Sends label images to a Brother QL printer.      connection_string:       - Netw (+70 more)

### Community 4 - "Community 4"
Cohesion: 0.04
Nodes (48): AttendanceRecordAdmin, CheckInConfigurationAdmin, CheckInWindowAdmin, CheckInWindowInline, CheckInConfigurationForm, CheckInSelectionForm, CheckInWindowForm, KioskLookupForm (+40 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (35): EventAdmin, EventOccurrenceInline, EventPhotoInline, EventRegistrationAdmin, EventRegistrationAttendeeInline, ReleaseDocumentAdmin, EventForm, EventOccurrenceForm (+27 more)

### Community 6 - "Community 6"
Cohesion: 0.04
Nodes (21): GroupDeleteViewTests, GroupDetailViewTests, GroupEditViewTests, GroupMemberAddTests, GroupMemberRemoveTests, GroupMemberSearchTests, make_staff_user(), HouseholdForm (+13 more)

### Community 7 - "Community 7"
Cohesion: 0.05
Nodes (70): Check-In Configuration Form Template, Check-In Configuration List Template, Attendance Kiosk Confirmation Template, Attendance Kiosk Family Select Template, Attendance Kiosk Lookup Template, Attendance Kiosk Unlock (PIN) Template, Attendee-to-Person Matching Queue Concept, Attendee Model (+62 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (48): AnchorPoint TODO List, Attendance Module (Legacy, Deprecated), BolivarSocialAccountAdapter (Custom OAuth Adapter), @checkin_admin_required Permission Decorator, CheckInConfiguration Model (Schedule + Eligibility + Rooms), Check-In Kiosk System (Tablet + Thermal Printer), CheckIn Module (Kiosk Check-In System), Check-In System Plan Document (+40 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (20): Meta, PersonForm, age(), formatted_address(), is_minor(), normalize_phone(), Strip all non-digit characters from a phone number., PeopleDetailCommunicationTests (+12 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (20): ABC, BasePrinterAdapter, BasePrinterAdapter, is_available(), print_image(), Base Printer Adapter  Abstract base class for all printer adapters., Base class for printer adapters., Initialize the printer adapter.          Args:             connection_string: (+12 more)

### Community 11 - "Community 11"
Cohesion: 0.1
Nodes (23): admin_required(), checkin_admin_required(), communications_required(), _get_user_profile(), has_communications_access(), is_admin(), is_checkin_admin(), is_staff_or_above() (+15 more)

### Community 12 - "Community 12"
Cohesion: 0.16
Nodes (25): _apply_contact_data(), create_person_from_attendee(), enroll_person_in_event_group(), ensure_event_group(), _ensure_household(), _ensure_person(), link_guardian_household(), manually_assign_attendee() (+17 more)

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (10): AppConfig, AttendanceConfig, CheckinConfig, CoreConfig, EventsConfig, GroupsConfig, HouseholdsConfig, MessagingConfig (+2 more)

### Community 14 - "Community 14"
Cohesion: 0.11
Nodes (24): AnchorPoint CLAUDE.md Developer Guide, Project Context Document, AnchorPoint Deployment Guide, AnchorPoint Church Management System, Cloudflare Tunnel, Django 5.2 Framework, Django REST Framework, Docker Compose Deployment (+16 more)

### Community 15 - "Community 15"
Cohesion: 0.17
Nodes (5): _grade_index(), is_person_eligible(), Return numeric index for grade comparison, or -1 if unknown., Check if a person is eligible for a check-in configuration.      All filters a, EligibilityTests

### Community 16 - "Community 16"
Cohesion: 0.18
Nodes (18): Base HTML Template, Kiosk PIN Security, OrganizationSettings Model, PhoneBlast Model, ReleaseDocument Model, Release Document Library, SMS Blackout Window, SmsMessage Model (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.29
Nodes (11): Event Model, Jingle Jam Christmas Celebration Event, Registration Model, Jingle Jam Christmas Event Photo, Email Base Template, Registration Confirmation Email (HTML), Registration Confirmation Email (Text), Staff New Registration Notification (HTML) (+3 more)

### Community 19 - "Community 19"
Cohesion: 0.31
Nodes (5): BaseCommand, Command, generate_password(), Management command to create beta test users for AnchorPoint.  Usage:     pyt, Generate a secure random password.

### Community 20 - "Community 20"
Cohesion: 0.33
Nodes (7): Migration, normalize_phone(), populate_normalized_phone(), Backfill normalized_phone for all existing Person records., Clear normalized_phone (reverse migration)., Strip all non-digit characters from a phone number., reverse_populate()

### Community 21 - "Community 21"
Cohesion: 0.5
Nodes (3): health_check(), URL configuration for anchorpoint project.  The `urlpatterns` list routes URLs, Simple health check endpoint for Docker/load balancer.

## Knowledge Gaps
- **246 isolated node(s):** `Run administrative tasks.`, `Simple health check endpoint for Docker/load balancer.`, `Dynamic form for selecting family members and rooms at check-in.`, `Return list of (person_id, room_id) for selected members.`, `Generate a 4-character random alphanumeric security code.` (+241 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **40 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Person` connect `Community 5` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 9`, `Community 11`, `Community 15`?**
  _High betweenness centrality (0.264) - this node is a cross-community bridge._
- **Why does `ESCPOSAdapter` connect `Community 3` to `Community 10`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Why does `LabelGeneratorTests` connect `Community 3` to `Community 0`, `Community 5`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 71 inferred relationships involving `Person` (e.g. with `CheckInConfiguration` and `Meta`) actually correct?**
  _`Person` has 71 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `Event` (e.g. with `OrganizationSettingsFormTests` and `ManageRolesViewTests`) actually correct?**
  _`Event` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `Room` (e.g. with `CheckInConfigurationAdmin` and `CheckInWindowAdmin`) actually correct?**
  _`Room` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `EventRegistration` (e.g. with `OrganizationSettingsFormTests` and `ManageRolesViewTests`) actually correct?**
  _`EventRegistration` has 34 INFERRED edges - model-reasoned connections that need verification._