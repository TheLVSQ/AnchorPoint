import re

from django import forms
from django.forms import inlineformset_factory

from .models import Event, EventOccurrence, EventPhoto, EventRegistration


class EventForm(forms.ModelForm):
    contact_phone = forms.CharField(
        label="Contact Phone",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "(555) 123-4567"}),
    )
    cost_amount = forms.DecimalField(
        label="Cost Amount",
        required=False,
        max_digits=8,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"placeholder": "25.00", "min": "0", "step": "0.01"}
        ),
    )

    class Meta:
        model = Event
        fields = [
            "title",
            "slug",
            "summary",
            "description",
            "location_name",
            "location_address_line1",
            "location_address_line2",
            "location_city",
            "location_state",
            "location_postal_code",
            "location_notes",
            "contact_name",
            "contact_email",
            "contact_phone",
            "is_free",
            "cost_amount",
            "registration_open",
            "registration_deadline",
            "registration_capacity",
            "is_published",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "location_notes": forms.Textarea(attrs={"rows": 3}),
            "registration_deadline": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "slug": forms.TextInput(
                attrs={
                    "placeholder": "e.g. christmas-concert-2025",
                }
            ),
            "title": forms.TextInput(attrs={"placeholder": "Event title"}),
            "location_name": forms.TextInput(attrs={"placeholder": "Venue or campus"}),
            "location_address_line1": forms.TextInput(attrs={"placeholder": "Street address"}),
            "location_address_line2": forms.TextInput(attrs={"placeholder": "Suite, building, etc."}),
            "location_city": forms.TextInput(attrs={"placeholder": "City"}),
            "location_state": forms.TextInput(attrs={"placeholder": "State / Province"}),
            "location_postal_code": forms.TextInput(attrs={"placeholder": "Postal code"}),
            "contact_name": forms.TextInput(attrs={"placeholder": "Point of contact"}),
            "contact_email": forms.EmailInput(attrs={"placeholder": "name@example.com"}),
        }
        help_texts = {
            "slug": "URL slug used for public links and embeds. Leave blank to auto-generate.",
        }
        labels = {
            "title": "Event Title",
            "slug": "URL Slug",
            "summary": "Summary",
            "description": "Description",
            "location_name": "Location Name",
            "location_address_line1": "Address Line 1",
            "location_address_line2": "Address Line 2",
            "location_city": "City",
            "location_state": "State / Province",
            "location_postal_code": "Postal Code",
            "location_notes": "Location Notes",
            "contact_name": "Contact Name",
            "contact_email": "Contact Email",
            "is_free": "Free Event",
            "registration_open": "Allow Registrations",
            "registration_deadline": "Registration Deadline",
            "registration_capacity": "Capacity Limit",
            "is_published": "Publish Event",
        }

    def clean(self):
        cleaned = super().clean()
        is_free = cleaned.get("is_free")
        cost_amount = cleaned.get("cost_amount")
        if not is_free and not cost_amount:
            self.add_error("cost_amount", "Enter a cost or mark the event as free.")
        if is_free:
            cleaned["cost_amount"] = None
        return cleaned

    def clean_contact_phone(self):
        phone = self.cleaned_data.get("contact_phone", "").strip()
        if not phone:
            return phone
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 10:
            raise forms.ValidationError(
                "Enter a valid phone number with at least 10 digits."
            )
        return phone


class EventOccurrenceForm(forms.ModelForm):
    class Meta:
        model = EventOccurrence
        fields = ["starts_at", "ends_at", "is_all_day"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")
        if starts_at and ends_at and ends_at < starts_at:
            self.add_error("ends_at", "End time must be after the start time.")
        return cleaned


class EventPhotoForm(forms.ModelForm):
    class Meta:
        model = EventPhoto
        fields = ["image", "caption", "display_order"]


EventOccurrenceFormSet = inlineformset_factory(
    Event,
    EventOccurrence,
    form=EventOccurrenceForm,
    extra=1,
    can_delete=True,
)

EventPhotoFormSet = inlineformset_factory(
    Event,
    EventPhoto,
    form=EventPhotoForm,
    extra=1,
    can_delete=True,
)


class EventRegistrationForm(forms.ModelForm):
    class Meta:
        model = EventRegistration
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "number_of_attendees",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
            "number_of_attendees": forms.NumberInput(attrs={"min": 1}),
        }

    def clean_number_of_attendees(self):
        value = self.cleaned_data.get("number_of_attendees") or 1
        if value < 1:
            raise forms.ValidationError("Please register at least one attendee.")
        return value
