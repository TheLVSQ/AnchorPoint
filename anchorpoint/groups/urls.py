from django.urls import path

from . import views

app_name = "groups"

urlpatterns = [
    path("", views.group_list, name="list"),
    path("new/", views.group_create, name="create"),
    path("<int:pk>/", views.group_detail, name="detail"),
    path("<int:pk>/edit/", views.group_edit, name="edit"),
    path("<int:pk>/delete/", views.group_delete, name="delete"),
    path("<int:pk>/members/add/", views.group_member_add, name="member_add"),
    path("<int:pk>/members/<int:mid>/remove/", views.group_member_remove, name="member_remove"),
    path("<int:pk>/member-search/", views.group_member_search, name="member_search"),
]
