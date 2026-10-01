import re

from django import forms
from django.forms import formset_factory, inlineformset_factory
from django.utils import timezone

from people.models import Person

from .models import (
    Event,
    EventOccurrence,
    EventPhoto,
    EventRegistration,
    EventRegistrationAttendee,
    ReleaseDocument,
)

STATE_CHOICES = [
    ("", "Select state"),
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("DC", "District of Columbia"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
]


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
            "cost_type",
            "liability_release_document",
            "liability_release_custom",
            "media_release_document",
            "media_release_custom",
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
            "cost_type": forms.Select(),
            "liability_release_document": forms.Select(),
            "media_release_document": forms.Select(),
        }
        help_texts = {
            "slug": "URL slug used for public links and embeds. Leave blank to auto-generate.",
            "cost_type": "Clarify how the amount applies so attendees know what to expect.",
            "liability_release_document": "Choose a standard liability release to display on the registration form.",
            "liability_release_custom": "Upload a unique liability release for this event (overrides the selection above).",
            "media_release_document": "Choose a standard media release.",
            "media_release_custom": "Upload a unique media release for this event (overrides the selection above).",
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
            "cost_type": "Cost Applies",
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


class EventRegistrationContactForm(forms.ModelForm):
    accept_liability = forms.BooleanField(
        label="I agree to the liability release",
        required=True,
    )
    liability_release_signature = forms.CharField(
        label="Type your full name to sign",
        required=True,
    )
    accept_media = forms.BooleanField(
        label="I agree to the photo/media release",
        required=False,
    )
    media_release_signature = forms.CharField(
        label="Type your full name to sign the photo/media release",
        required=False,
    )

    class Meta:
        model = EventRegistration
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "birthdate",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
            "birthdate": forms.DateInput(attrs={"type": "date"}),
            "state": forms.Select(choices=STATE_CHOICES),
        }
        labels = {
            "birthdate": "Date of Birth",
        }
        help_texts = {
            "notes": "Any special requests or details our team should know.",
        }

    def clean(self):
        cleaned = super().clean()
        accept_media = cleaned.get("accept_media")
        media_signature = cleaned.get("media_release_signature", "").strip()
        if accept_media and not media_signature:
            self.add_error(
                "media_release_signature",
                "Type your name to sign the photo/media release.",
            )
        return cleaned

    def apply_release_metadata(self, registration, ip_address="", user_agent=""):
        signature = self.cleaned_data.get("liability_release_signature", "").strip()
        if self.cleaned_data.get("accept_liability"):
            registration.liability_release_accepted_at = timezone.now()
            registration.liability_release_name = signature or registration.first_name
            registration.liability_release_ip = ip_address or None
            registration.liability_release_user_agent = user_agent or ""
        else:
            registration.liability_release_accepted_at = None
            registration.liability_release_name = ""
            registration.liability_release_ip = None
            registration.liability_release_user_agent = ""

        media_signature = self.cleaned_data.get("media_release_signature", "").strip()
        if self.cleaned_data.get("accept_media"):
            registration.media_release_accepted_at = timezone.now()
            registration.media_release_name = media_signature or signature
            registration.media_release_ip = ip_address or None
            registration.media_release_user_agent = user_agent or ""
        else:
            registration.media_release_accepted_at = None
            registration.media_release_name = ""
            registration.media_release_ip = None
            registration.media_release_user_agent = ""


class EventRegistrationAttendeeForm(forms.ModelForm):
    grade = forms.ChoiceField(
        choices=[("", "Select grade")] + list(Person.GRADE_CHOICES),
        required=False,
        label="Grade (if applicable)",
    )
    emergency_contact_relationship = forms.CharField(
        required=False,
        initial="Parent/Guardian",
        label="Emergency Contact Relationship",
    )

    class Meta:
        model = EventRegistrationAttendee
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "birthdate",
            "is_minor",
            "grade",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "parent_guardian_name",
            "parent_guardian_email",
            "parent_guardian_phone",
            "allergies",
            "medical_notes",
            "emergency_contact_name",
            "emergency_contact_relationship",
            "emergency_contact_phone",
            "notes",
        ]
        widgets = {
            "birthdate": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "allergies": forms.Textarea(attrs={"rows": 2}),
            "medical_notes": forms.Textarea(attrs={"rows": 2}),
            "state": forms.Select(choices=STATE_CHOICES),
        }
        labels = {
            "is_minor": "Is this attendee a minor?",
            "grade": "Grade (if applicable)",
            "parent_guardian_name": "Parent / Guardian Name",
        }

    def clean(self):
        cleaned = super().clean()
        is_minor = cleaned.get("is_minor")
        if is_minor:
            required_fields = {
                "parent_guardian_name": "Parent or guardian name is required for minors.",
                "parent_guardian_phone": "Parent or guardian phone is required for minors.",
                "emergency_contact_name": "Emergency contact is required for minors.",
                "emergency_contact_phone": "Emergency contact phone is required for minors.",
            }
            for field, message in required_fields.items():
                value = cleaned.get(field)
                if not value:
                    self.add_error(field, message)
        return cleaned


EventRegistrationAttendeeFormSet = formset_factory(
    EventRegistrationAttendeeForm,
    extra=1,
    min_num=1,
    validate_min=True,
)


class RegistrationMatchForm(forms.Form):
    ACTION_ASSIGN = "assign"
    ACTION_CREATE = "create"
    ACTION_DISMISS = "dismiss"
    ACTION_CHOICES = [
        (ACTION_ASSIGN, "Link to selected person"),
        (ACTION_CREATE, "Create new person from attendee"),
        (ACTION_DISMISS, "Dismiss for now"),
    ]

    person = forms.ModelChoiceField(
        queryset=Person.objects.all().order_by("last_name", "first_name"),
        required=False,
        label="Link to Person",
    )
    action = forms.ChoiceField(choices=ACTION_CHOICES, initial=ACTION_ASSIGN)
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Notes",
    )

    def __init__(self, attendee, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attendee = attendee

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("action")
        person = cleaned.get("person")
        if action == self.ACTION_ASSIGN and not person:
            self.add_error("person", "Select a person to link this attendee.")
        return cleaned


class ReleaseDocumentForm(forms.ModelForm):
    class Meta:
        model = ReleaseDocument
        fields = ["name", "category", "file", "description"]
