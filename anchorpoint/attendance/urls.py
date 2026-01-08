from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path(
        "configurations/",
        views.configuration_list,
        name="configuration_list",
    ),
    path(
        "configurations/new/",
        views.configuration_create,
        name="configuration_create",
    ),
    path(
        "configurations/<int:pk>/",
        views.configuration_edit,
        name="configuration_edit",
    ),
    path(
        "kiosk/",
        views.kiosk_lookup,
        name="kiosk_lookup",
    ),
    path(
        "kiosk/unlock/",
        views.kiosk_unlock,
        name="kiosk_unlock",
    ),
    path(
        "kiosk/lock/",
        views.kiosk_lock,
        name="kiosk_lock",
    ),
    path(
        "kiosk/family/<int:pk>/",
        views.kiosk_family_select,
        name="kiosk_family_select",
    ),
    path(
        "kiosk/confirmation/",
        views.kiosk_confirmation,
        name="kiosk_confirmation",
    ),
]
