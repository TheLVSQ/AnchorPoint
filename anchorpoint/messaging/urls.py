from django.urls import path

from . import views


app_name = "messaging"

urlpatterns = [
    path("", views.communications_home, name="home"),
    path("sms/new/", views.sms_compose, name="sms_compose"),
    path("phone-blasts/new/", views.phone_blast_create, name="phone_blast_create"),
]
