from django.urls import path

from . import views

app_name = "scheduling"

urlpatterns = [
    path("serving/", views.my_serving, name="my_serving"),
    path("serving/teams/<int:mid>/", views.my_serving_weeks, name="my_serving_weeks"),
    path("serving/blockouts/add/", views.my_blockout_add, name="my_blockout_add"),
    path("serving/blockouts/<int:pk>/delete/", views.my_blockout_delete,
         name="my_blockout_delete"),
    path("people/<int:person_id>/blockouts/add/", views.person_blockout_add,
         name="person_blockout_add"),
    path("people/<int:person_id>/blockouts/<int:pk>/delete/", views.person_blockout_delete,
         name="person_blockout_delete"),
]
