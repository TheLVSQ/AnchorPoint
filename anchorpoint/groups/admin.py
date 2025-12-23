from django.contrib import admin

from .models import Group, GroupMembership


class GroupMembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 0


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "location", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description", "location", "short_code")
    inlines = [GroupMembershipInline]


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ("group", "person", "role", "joined_at")
    list_filter = ("role", "group__category")
    search_fields = ("group__name", "person__first_name", "person__last_name")
