from django.urls import path

from . import views
from . import print_api

app_name = "checkin"

urlpatterns = [
    # Kiosk (public, PIN-gated)
    path("kiosk/", views.kiosk_lookup, name="kiosk_lookup"),
    path("kiosk/unlock/", views.kiosk_unlock, name="kiosk_unlock"),
    path("kiosk/lock/", views.kiosk_lock, name="kiosk_lock"),
    path("kiosk/select-config/", views.kiosk_select_config, name="kiosk_select_config"),
    path("kiosk/family/<int:household_id>/", views.kiosk_family_select, name="kiosk_family_select"),
    path("kiosk/confirmation/", views.kiosk_confirmation, name="kiosk_confirmation"),
    path("kiosk/register/", views.kiosk_quick_register, name="kiosk_quick_register"),

    # Checkout (login required)
    path("checkout/<int:session_id>/", views.checkout_lookup, name="checkout_lookup"),
    path("checkout/<int:session_id>/confirm/", views.checkout_confirm, name="checkout_confirm"),

    # Configuration admin (checkin_admin_required)
    path("configurations/", views.configuration_list, name="configuration_list"),
    path("configurations/new/", views.configuration_create, name="configuration_create"),
    path("configurations/<int:pk>/", views.configuration_edit, name="configuration_edit"),
    path("configurations/<int:pk>/delete/", views.configuration_delete, name="configuration_delete"),

    # Dashboard and admin (staff_required)
    path("", views.dashboard, name="dashboard"),
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/new/", views.session_create, name="session_create"),
    path("sessions/<int:session_id>/", views.session_detail, name="session_detail"),
    path("sessions/<int:session_id>/edit/", views.session_edit, name="session_edit"),
    path("sessions/<int:session_id>/stats/", views.session_stats, name="session_stats"),

    # Room management
    path("rooms/", views.room_list, name="room_list"),
    path("rooms/new/", views.room_create, name="room_create"),
    path("rooms/<int:room_id>/edit/", views.room_edit, name="room_edit"),

    # Printer management
    path("printers/", views.printer_list, name="printer_list"),
    path("printers/new/", views.printer_create, name="printer_create"),
    path("printers/<int:printer_id>/edit/", views.printer_edit, name="printer_edit"),
    path("printers/<int:printer_id>/test/", views.printer_test, name="printer_test"),

    # Print agents (pull-based local printing; surfaced in Settings)
    path("agents/", views.print_agent_list, name="print_agents"),
    path("agents/new/", views.print_agent_create, name="print_agent_create"),
    path("agents/<int:agent_id>/repair/", views.print_agent_repair, name="print_agent_repair"),
    path("agents/<int:agent_id>/delete/", views.print_agent_delete, name="print_agent_delete"),
    path("agents/<int:agent_id>/test/", views.print_agent_test, name="print_agent_test"),

    # API
    path("api/sessions/<int:session_id>/stats/", views.api_session_stats, name="api_session_stats"),

    # Agent-facing print API (token auth)
    path("api/print/pair", print_api.pair, name="print_pair"),
    path("api/print/next", print_api.next_job, name="print_next"),
    path("api/print/<int:job_id>/image", print_api.job_image, name="print_job_image"),
    path("api/print/<int:job_id>/ack", print_api.ack_job, name="print_ack"),
]
