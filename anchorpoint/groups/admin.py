from django.contrib import admin

from .models import Group


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "location", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description", "location", "short_code")
