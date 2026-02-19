from django.urls import path
from . import views

app_name = "checkin"

urlpatterns = [
    # Kiosk views (public-facing)
    path("kiosk/", views.kiosk_home, name="kiosk_home"),
    path("kiosk/<int:session_id>/lookup/", views.kiosk_lookup, name="kiosk_lookup"),
    path("kiosk/<int:session_id>/select/", views.kiosk_select, name="kiosk_select"),
    path("kiosk/<int:session_id>/rooms/", views.kiosk_rooms, name="kiosk_rooms"),
    path("kiosk/<int:session_id>/complete/", views.kiosk_complete, name="kiosk_complete"),

    # Checkout views (volunteer-facing)
    path("checkout/<int:session_id>/", views.checkout_lookup, name="checkout_lookup"),
    path("checkout/<int:session_id>/confirm/", views.checkout_confirm, name="checkout_confirm"),

    # Dashboard and admin views (staff-facing)
    path("", views.dashboard, name="dashboard"),
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/new/", views.session_create, name="session_create"),
    path("sessions/<int:session_id>/", views.session_detail, name="session_detail"),
    path("sessions/<int:session_id>/edit/", views.session_edit, name="session_edit"),

    # Room management
    path("rooms/", views.room_list, name="room_list"),
    path("rooms/new/", views.room_create, name="room_create"),
    path("rooms/<int:room_id>/edit/", views.room_edit, name="room_edit"),

    # Printer management
    path("printers/", views.printer_list, name="printer_list"),
    path("printers/new/", views.printer_create, name="printer_create"),
    path("printers/<int:printer_id>/edit/", views.printer_edit, name="printer_edit"),
    path("printers/<int:printer_id>/test/", views.printer_test, name="printer_test"),

    # API endpoints
    path("api/sessions/<int:session_id>/stats/", views.api_session_stats, name="api_session_stats"),
]
