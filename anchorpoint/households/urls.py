from django.urls import path

from . import views

app_name = "households"

urlpatterns = [
    path("", views.family_list, name="family_list"),
    path("review/", views.family_flags, name="family_flags"),
    path("review/<int:pk>/undo/", views.family_flag_undo, name="family_flag_undo"),
    path("review/<int:pk>/ok/", views.family_flag_reviewed, name="family_flag_reviewed"),
    path("cleanup/", views.cleanup_list, name="cleanup_list"),
    path("cleanup/<int:pk>/merge/", views.cleanup_merge, name="cleanup_merge"),
    path("cleanup/<int:pk>/delete/", views.cleanup_delete_household, name="cleanup_delete_household"),
    path("cleanup/<int:pk>/dismiss/", views.cleanup_dismiss, name="cleanup_dismiss"),
    path("cleanup/<int:pk>/reopen/", views.cleanup_reopen, name="cleanup_reopen"),
    path("<int:pk>/", views.family_detail, name="family_detail"),
    path("<int:pk>/edit/", views.family_edit, name="family_edit"),
    path("<int:pk>/delete/", views.family_delete, name="family_delete"),
    path("<int:pk>/members/add/", views.family_member_add, name="family_member_add"),
    path("<int:pk>/members/new/", views.family_member_create, name="family_member_create"),
    path("<int:pk>/members/<int:member_pk>/remove/", views.family_member_remove, name="family_member_remove"),
    path("<int:pk>/members/<int:member_pk>/role/", views.family_member_role, name="family_member_role"),
    path("<int:pk>/primary/", views.family_set_primary, name="family_set_primary"),
]
