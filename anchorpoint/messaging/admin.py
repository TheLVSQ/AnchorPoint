from django.contrib import admin

from .models import Communication, Delivery


class DeliveryInline(admin.TabularInline):
    model = Delivery
    extra = 0
    fields = ("person", "address", "status", "skip_reason", "provider_id", "error_message", "sent_at")
    readonly_fields = fields
    can_delete = False


@admin.register(Communication)
class CommunicationAdmin(admin.ModelAdmin):
    list_display = ("id", "channel", "kind", "title", "status", "created_by", "scheduled_for", "created_at")
    list_filter = ("channel", "kind", "status")
    search_fields = ("title", "body", "created_by__username")
    date_hierarchy = "created_at"
    inlines = [DeliveryInline]


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ("communication", "person", "address", "status", "skip_reason", "sent_at")
    list_filter = ("status", "skip_reason", "communication__channel")
    search_fields = ("person__first_name", "person__last_name", "address", "provider_id")
