from django.urls import path

from . import views


app_name = "messaging"

urlpatterns = [
    path("", views.communications_home, name="home"),
    path("sms/new/", views.sms_compose, name="sms_compose"),
    path("phone-blasts/new/", views.phone_blast_create, name="phone_blast_create"),
    path("phone-blast/webhook/call-status/", views.phone_call_status_webhook, name="phone_call_status_webhook"),
    path("phone-blast/<int:pk>/", views.phone_blast_detail, name="phone_blast_detail"),
    path("phone-blast/<int:pk>/stats/", views.phone_blast_stats, name="phone_blast_stats"),
]
