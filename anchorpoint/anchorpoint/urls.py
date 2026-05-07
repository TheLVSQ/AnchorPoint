"""
URL configuration for anchorpoint project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from core import views as core_views
from events import views as event_views


def health_check(request):
    """Simple health check endpoint for Docker/load balancer."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("admin/", admin.site.urls),
    path("login/", core_views.login_view, name="login"),
    path("logout/", core_views.logout_view, name="logout"),
    path("auth/google/", core_views.google_auth_callback, name="google_auth"),
    path("", core_views.dashboard, name="dashboard"),
    path("profile/", core_views.profile, name="profile"),
    path("permissions/roles/", core_views.manage_roles, name="manage_roles"),
    path("users/", core_views.user_list, name="user_list"),
    path("users/new/", core_views.user_create, name="user_create"),
    path("users/<int:user_id>/edit/", core_views.user_edit, name="user_edit"),
    path("users/<int:user_id>/password/", core_views.user_set_password, name="user_set_password"),
    path("settings/", core_views.settings_home, name="settings_home"),
    path(
        "settings/organization/",
        core_views.organization_settings,
        name="organization_settings",
    ),
    path("people/", include("people.urls")),
    path("groups/", include("groups.urls")),
    path("events/", include("events.urls")),
    path("communications/", include(("messaging.urls", "messaging"), namespace="messaging")),
    path("checkin/", include(("checkin.urls", "checkin"), namespace="checkin")),
    path(
        "register/<uuid:registration_token>/",
        event_views.public_event_register,
        name="event_register",
    ),
]

# Serve media files directly — Django's static() helper only works with DEBUG=True,
# so we wire up the serve view explicitly for production compatibility.
# For high-traffic deployments replace this with nginx or a CDN.
from django.views.static import serve
from django.urls import re_path
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
