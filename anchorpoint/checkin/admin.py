from django.contrib import admin
from .models import Room, CheckInSession, CheckIn, PrinterConfiguration, LabelTemplate


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["name", "building", "capacity", "min_age", "max_age", "sort_order", "is_active"]
    list_filter = ["is_active", "building"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "building"]
    ordering = ["sort_order", "name"]


@admin.register(CheckInSession)
class CheckInSessionAdmin(admin.ModelAdmin):
    list_display = ["name", "date", "start_time", "end_time", "is_active", "total_checked_in"]
    list_filter = ["is_active", "date"]
    search_fields = ["name"]
    date_hierarchy = "date"
    filter_horizontal = ["rooms"]
    readonly_fields = ["created_at", "created_by"]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    list_display = [
        "person",
        "session",
        "room",
        "security_code",
        "checked_in_at",
        "is_checked_out",
    ]
    list_filter = ["session", "room", "checked_out_at"]
    search_fields = [
        "person__first_name",
        "person__last_name",
        "security_code",
    ]
    raw_id_fields = ["person", "session"]
    readonly_fields = ["checked_in_at", "checked_in_by", "checked_out_at", "checked_out_by"]

    def is_checked_out(self, obj):
        return obj.is_checked_out
    is_checked_out.boolean = True


@admin.register(PrinterConfiguration)
class PrinterConfigurationAdmin(admin.ModelAdmin):
    list_display = ["name", "printer_type", "connection_string", "is_default", "is_active"]
    list_filter = ["printer_type", "is_active", "is_default"]
    list_editable = ["is_active"]


@admin.register(LabelTemplate)
class LabelTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "label_type", "is_default"]
    list_filter = ["label_type", "is_default"]
