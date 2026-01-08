from django.contrib import admin

from .models import AttendanceRecord, CheckInConfiguration, CheckInWindow


class CheckInWindowInline(admin.TabularInline):
    model = CheckInWindow
    extra = 1
    fields = (
        "schedule_type",
        "day_of_week",
        "specific_date",
        "opens_at",
        "closes_at",
        "is_active",
        "notes",
    )


@admin.register(CheckInConfiguration)
class CheckInConfigurationAdmin(admin.ModelAdmin):
    list_display = ("name", "location_name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "location_name")
    filter_horizontal = ("groups",)
    inlines = [CheckInWindowInline]


@admin.register(CheckInWindow)
class CheckInWindowAdmin(admin.ModelAdmin):
    list_display = (
        "configuration",
        "schedule_type",
        "day_of_week",
        "specific_date",
        "opens_at",
        "closes_at",
        "is_active",
    )
    list_filter = ("schedule_type", "day_of_week", "is_active")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "person",
        "group",
        "configuration",
        "checked_in_at",
        "method",
    )
    list_filter = ("configuration", "method")
    search_fields = ("person__first_name", "person__last_name")
