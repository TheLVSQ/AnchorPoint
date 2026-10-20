from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("manage/", views.event_manage_list, name="manage_list"),
    path("manage/create/", views.event_create, name="create"),
    path("manage/<int:pk>/edit/", views.event_edit, name="edit"),
    path(
        "manage/<int:pk>/registrations/",
        views.event_registrations,
        name="registrations",
    ),
    path(
        "manage/<int:pk>/roster/",
        views.event_roster,
        name="roster",
    ),
    path(
        "manage/<int:pk>/roster.csv",
        views.event_roster_export,
        name="roster_export",
    ),
    path(
        "manage/registrations/queue/",
        views.event_registration_queue,
        name="registration_queue",
    ),
    path("feed.json", views.public_events_feed_json, name="feed_json"),
    path("feed.ics", views.public_events_feed_ics, name="feed_ics"),
    path("", views.public_event_list, name="public_list"),
    path("<slug:slug>/", views.public_event_detail, name="public_detail"),
]
