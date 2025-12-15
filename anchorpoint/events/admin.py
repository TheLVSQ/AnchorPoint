from django.contrib import admin

from .models import Event, EventOccurrence, EventPhoto, EventRegistration


class EventOccurrenceInline(admin.TabularInline):
    model = EventOccurrence
    extra = 1


class EventPhotoInline(admin.TabularInline):
    model = EventPhoto
    extra = 1


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "registration_open", "created_at")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [EventOccurrenceInline, EventPhotoInline]
    search_fields = ("title", "summary", "description")
    list_filter = ("is_published", "registration_open", "is_free")


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = ("event", "first_name", "last_name", "email", "created_at")
    search_fields = ("first_name", "last_name", "email", "event__title")
    list_filter = ("created_at",)
