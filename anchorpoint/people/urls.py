from django.urls import path
from . import views

urlpatterns = [
    path("", views.people_list, name="people_list"),
    path("add/", views.people_add, name="people_add"),
    path("lookup/", views.people_lookup, name="people_lookup"),
    path("<int:pk>/", views.people_detail, name="people_detail"),
    path("<int:pk>/edit/", views.people_edit, name="people_edit"),
    path(
        "<int:pk>/households/add/",
        views.people_household_add,
        name="people_household_add",
    ),
    path(
        "<int:pk>/households/create/",
        views.people_household_create,
        name="people_household_create",
    ),
    path(
        "<int:pk>/households/<int:household_pk>/remove/",
        views.people_household_remove,
        name="people_household_remove",
    ),
]
