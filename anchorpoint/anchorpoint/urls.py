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
from django.urls import include, path
from core import views as core_views
from events import views as event_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", core_views.login_view, name="login"),
    path("logout/", core_views.logout_view, name="logout"),
    path("", core_views.dashboard, name="dashboard"),
    path("profile/", core_views.profile, name="profile"),
    path("permissions/roles/", core_views.manage_roles, name="manage_roles"),
    path("settings/", core_views.settings_home, name="settings_home"),
    path(
        "settings/organization/",
        core_views.organization_settings,
        name="organization_settings",
    ),
    path("people/", include("people.urls")),
    path("groups/", include("groups.urls")),
    path("events/", include("events.urls")),
    path(
        "register/<uuid:registration_token>/",
        event_views.public_event_register,
        name="event_register",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
