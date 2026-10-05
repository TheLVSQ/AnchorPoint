from django.urls import path

from . import views

app_name = "help"

urlpatterns = [
    path("", views.guide_list, name="list"),
    path("<slug:slug>/", views.guide_detail, name="guide"),
]
