from django.contrib import admin

from .models import CommunicationLog, PhoneBlast, PhoneCall, SmsMessage, SmsRecipient


@admin.register(SmsMessage)
class SmsMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "created_by", "target_type", "status", "scheduled_for", "sent_at")
    list_filter = ("status", "target_type")
    search_fields = ("body", "created_by__username")
    date_hierarchy = "created_at"


@admin.register(SmsRecipient)
class SmsRecipientAdmin(admin.ModelAdmin):
    list_display = ("message", "person", "phone_number", "status", "sent_at")
    list_filter = ("status",)
    search_fields = ("person__first_name", "person__last_name", "phone_number")


@admin.register(PhoneBlast)
class PhoneBlastAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "status", "scheduled_for", "started_at")
    list_filter = ("status",)
    search_fields = ("title", "group__name")
    date_hierarchy = "created_at"


@admin.register(PhoneCall)
class PhoneCallAdmin(admin.ModelAdmin):
    list_display = ("blast", "person", "phone_number", "status")
    list_filter = ("status",)
    search_fields = ("person__first_name", "person__last_name", "phone_number")


@admin.register(CommunicationLog)
class CommunicationLogAdmin(admin.ModelAdmin):
    list_display = ("person", "communication_type", "summary", "recorded_by", "created_at")
    list_filter = ("communication_type",)
    search_fields = ("person__first_name", "person__last_name", "summary")
