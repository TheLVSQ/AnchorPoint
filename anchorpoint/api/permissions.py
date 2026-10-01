from rest_framework.permissions import BasePermission

from core.models import UserProfile


class IsStaffOrAdmin(BasePermission):
    message = "You do not have staff access."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        if not profile:
            return False
        return profile.role in {
            UserProfile.Role.ADMIN,
            UserProfile.Role.STAFF,
            UserProfile.Role.VOLUNTEER_ADMIN,
        }


class IsAdminUserProfile(BasePermission):
    message = "You do not have admin access."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.role == UserProfile.Role.ADMIN)
