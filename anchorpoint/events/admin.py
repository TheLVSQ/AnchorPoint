from django.contrib import admin

from .models import (
    Event,
    EventOccurrence,
    EventPhoto,
    EventRegistration,
    EventRegistrationAttendee,
    ReleaseDocument,
)


class EventOccurrenceInline(admin.TabularInline):
    model = EventOccurrence
    extra = 1


class EventPhotoInline(admin.TabularInline):
    model = EventPhoto
    extra = 1


class EventRegistrationAttendeeInline(admin.StackedInline):
    model = EventRegistrationAttendee
    extra = 0
    classes = ["collapse"]
    fieldsets = (
        (
            "Attendee",
            {
                "fields": (
                    ("first_name", "last_name", "is_minor", "grade"),
                    ("email", "phone"),
                    ("birthdate",),
                    ("person", "group"),
                    "notes",
                )
            },
        ),
        (
            "Contact & Address",
            {
                "fields": (
                    ("address_line1", "address_line2"),
                    ("city", "state", "postal_code"),
                    ("parent_guardian_name", "parent_guardian_phone"),
                    ("parent_guardian_email",),
                ),
                "classes": ["collapse"],
            },
        ),
        (
            "Health & Emergency",
            {
                "fields": (
                    "allergies",
                    "medical_notes",
                    ("emergency_contact_name", "emergency_contact_relationship"),
                    ("emergency_contact_phone",),
                ),
                "classes": ["collapse"],
            },
        ),
    )


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
    list_filter = ("created_at", "event")
    inlines = [EventRegistrationAttendeeInline]


@admin.register(ReleaseDocument)
class ReleaseDocumentAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "updated_at")
    list_filter = ("category",)
    search_fields = ("name", "description")
