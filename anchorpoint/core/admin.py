from django.contrib import admin

from .models import OrganizationSettings, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "can_manage_communications", "is_admin_flag")
    list_filter = ("role", "can_manage_communications")
    search_fields = ("user__username", "user__first_name", "user__last_name")

    def is_admin_flag(self, obj):
        return obj.is_admin

    is_admin_flag.boolean = True
    is_admin_flag.short_description = "Is Admin"


@admin.register(OrganizationSettings)
class OrganizationSettingsAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_number", "email", "updated_at")
    readonly_fields = ("created_at", "updated_at")
