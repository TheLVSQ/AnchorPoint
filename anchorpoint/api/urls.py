from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ApiMeView, ApiRootView
from .viewsets import (
    CheckInSessionViewSet,
    EventViewSet,
    GroupViewSet,
    HouseholdViewSet,
    PersonViewSet,
)


app_name = "api"

router = DefaultRouter()
router.register("people", PersonViewSet, basename="person")
router.register("households", HouseholdViewSet, basename="household")
router.register("groups", GroupViewSet, basename="group")
router.register("events", EventViewSet, basename="event")
router.register("checkin/sessions", CheckInSessionViewSet, basename="checkin-session")

urlpatterns = [
    path("", ApiRootView.as_view(), name="root"),
    path("me/", ApiMeView.as_view(), name="me"),
    path("", include(router.urls)),
]
