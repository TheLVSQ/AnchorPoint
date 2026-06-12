from django.urls import path

from . import views

app_name = "households"

urlpatterns = [
    path("", views.family_list, name="family_list"),
    path("<int:pk>/", views.family_detail, name="family_detail"),
    path("<int:pk>/edit/", views.family_edit, name="family_edit"),
    path("<int:pk>/members/add/", views.family_member_add, name="family_member_add"),
    path("<int:pk>/members/<int:member_pk>/remove/", views.family_member_remove, name="family_member_remove"),
    path("<int:pk>/members/<int:member_pk>/role/", views.family_member_role, name="family_member_role"),
    path("<int:pk>/primary/", views.family_set_primary, name="family_set_primary"),
]
