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

    # Staff: service types, plans, the schedule grid
    path("plans/", views.service_type_list, name="service_type_list"),
    path("plans/types/new/", views.service_type_form, name="service_type_create"),
    path("plans/types/<int:pk>/", views.schedule_grid, name="schedule"),
    path("plans/types/<int:pk>/edit/", views.service_type_form, name="service_type_edit"),
    path("plans/types/<int:pk>/dates/", views.plans_add, name="plans_add"),
    path("plans/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("plans/<int:pk>/delete/", views.plan_delete, name="plan_delete"),
    path("plans/<int:pk>/positions/<int:position_id>/", views.cell, name="cell"),
    path("plans/<int:pk>/positions/<int:position_id>/pick/", views.cell_pick, name="cell_pick"),
    path("plans/<int:pk>/positions/<int:position_id>/assign/", views.cell_assign,
         name="cell_assign"),
    path("plans/assignments/<int:pk>/remove/", views.assignment_remove,
         name="assignment_remove"),
]
