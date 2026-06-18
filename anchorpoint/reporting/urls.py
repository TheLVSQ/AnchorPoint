from django.urls import path

from . import views

app_name = "reporting"

urlpatterns = [
    path("", views.report_list, name="list"),
    path("<slug:slug>/", views.report_detail, name="detail"),
    path("<slug:slug>/export/", views.report_export, name="export"),
]
