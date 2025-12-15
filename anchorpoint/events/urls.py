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
    path("", views.public_event_list, name="public_list"),
    path("<slug:slug>/", views.public_event_detail, name="public_detail"),
]
