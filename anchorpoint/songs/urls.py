from django.urls import path

from . import views

app_name = "songs"

urlpatterns = [
    path("", views.song_list, name="list"),
    path("new/", views.song_form, name="create"),
    path("<int:pk>/", views.song_detail, name="detail"),
    path("<int:pk>/edit/", views.song_form, name="edit"),
    path("<int:pk>/archive/", views.song_archive, name="archive"),
    path("<int:song_pk>/arrangements/new/", views.arrangement_form, name="arrangement_create"),
    path("arrangements/<int:pk>/edit/", views.arrangement_form, name="arrangement_edit"),
    path("arrangements/<int:pk>/delete/", views.arrangement_delete, name="arrangement_delete"),
    path("arrangements/<int:arrangement_pk>/charts/", views.chart_add, name="chart_add"),
    path("charts/<int:pk>/", views.chart_view, name="chart"),
    path("charts/<int:pk>/delete/", views.chart_delete, name="chart_delete"),
    path("arrangements/<int:arrangement_pk>/links/", views.link_add, name="link_add"),
    path("links/<int:pk>/delete/", views.link_delete, name="link_delete"),
]
