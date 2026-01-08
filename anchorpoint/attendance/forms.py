from django import forms
from django.forms import inlineformset_factory

from groups.models import Group

from .models import CheckInConfiguration, CheckInWindow


def normalize_phone_digits(value):
    if not value:
        return ""
    return "".join(ch for ch in value if ch.isdigit())


class CheckInConfigurationForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.none(),
        required=False,
        help_text="Pick which groups/classrooms should appear on this kiosk.",
        widget=forms.SelectMultiple(attrs={"size": 8}),
    )

    class Meta:
        model = CheckInConfiguration
        fields = [
            "name",
            "description",
            "welcome_message",
            "location_name",
            "is_active",
            "groups",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "welcome_message": forms.TextInput(attrs={"placeholder": "Welcome to church!"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["groups"].queryset = Group.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["groups"].label = "Eligible Groups"


class CheckInWindowForm(forms.ModelForm):
    class Meta:
        model = CheckInWindow
        fields = [
            "schedule_type",
            "day_of_week",
            "specific_date",
            "opens_at",
            "closes_at",
            "is_active",
            "notes",
        ]
        widgets = {
            "schedule_type": forms.Select(attrs={"data-schedule-type-select": "true"}),
            "day_of_week": forms.Select(),
            "specific_date": forms.DateInput(attrs={"type": "date"}),
            "opens_at": forms.TimeInput(attrs={"type": "time"}),
            "closes_at": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.TextInput(attrs={"placeholder": "Optional reminder"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        opens_at = cleaned_data.get("opens_at")
        closes_at = cleaned_data.get("closes_at")
        if opens_at and closes_at and opens_at >= closes_at:
            self.add_error("closes_at", "Close time must be after start time.")
        return cleaned_data


CheckInWindowFormSet = inlineformset_factory(
    CheckInConfiguration,
    CheckInWindow,
    form=CheckInWindowForm,
    fields=[
        "schedule_type",
        "day_of_week",
        "specific_date",
        "opens_at",
        "closes_at",
        "is_active",
        "notes",
    ],
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class KioskLookupForm(forms.Form):
    query = forms.CharField(
        required=False,
        label="Phone or Last Name",
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. 417-555-1212 or Smith",
                "autofocus": True,
            }
        ),
        help_text="Type a 10-digit phone number or the family last name.",
    )

    def clean(self):
        cleaned_data = super().clean()
        raw = (cleaned_data.get("query") or "").strip()
        if not raw:
            raise forms.ValidationError("Enter a phone number or last name to search.")

        digits = normalize_phone_digits(raw)
        alpha = "".join(
            ch for ch in raw if ch.isalpha() or ch.isspace() or ch == "-"
        ).strip()

        last_name = alpha if alpha and any(c.isalpha() for c in alpha) else ""
        phone_digits = digits

        if not last_name and not phone_digits:
            raise forms.ValidationError(
                "Include letters for a last name or digits for a phone number."
            )

        cleaned_data["query"] = raw
        cleaned_data["last_name"] = last_name
        cleaned_data["phone_digits"] = phone_digits
        return cleaned_data


class KioskPinForm(forms.Form):
    pin = forms.CharField(
        label="Enter PIN",
        widget=forms.PasswordInput(attrs={"placeholder": "****", "inputmode": "numeric"}),
    )

    def __init__(self, *args, expected_pin="", **kwargs):
        self.expected_pin = (expected_pin or "").strip()
        super().__init__(*args, **kwargs)

    def clean_pin(self):
        value = self.cleaned_data["pin"]
        if not value:
            raise forms.ValidationError("Enter the PIN to continue.")
        return value.strip()

    def clean(self):
        cleaned_data = super().clean()
        if self.expected_pin and cleaned_data.get("pin") != self.expected_pin:
            raise forms.ValidationError("Incorrect PIN.")
        return cleaned_data


class CheckInSelectionForm(forms.Form):
    person_ids = forms.TypedMultipleChoiceField(
        coerce=int,
        required=True,
        error_messages={"required": "Select at least one individual."},
    )
    window_id = forms.TypedChoiceField(
        coerce=int,
        required=True,
        error_messages={"required": "Select an active check-in window."},
    )

    def __init__(
        self,
        *args,
        person_choices=None,
        window_choices=None,
        person_group_map=None,
        window_group_map=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields["person_ids"].choices = person_choices or []
        self.fields["window_id"].choices = window_choices or []
        self.person_group_map = person_group_map or {}
        self.window_group_map = window_group_map or {}

    def clean(self):
        cleaned_data = super().clean()
        person_ids = cleaned_data.get("person_ids")
        window_id = cleaned_data.get("window_id")
        if not person_ids or window_id is None:
            return cleaned_data
        window_groups = self.window_group_map.get(window_id, set())
        if not window_groups:
            self.add_error("window_id", "Select an active check-in window.")
            return cleaned_data
        invalid_people = [
            person_id
            for person_id in person_ids
            if not set(self.person_group_map.get(person_id, set())).intersection(window_groups)
        ]
        if invalid_people:
            raise forms.ValidationError(
                "One or more selected individuals are not eligible for the chosen check-in."
            )
        return cleaned_data
