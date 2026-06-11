from django import forms
from django.forms import inlineformset_factory

from .models import CheckInConfiguration, CheckInSession, CheckInWindow, Room, PrinterConfiguration


class CheckInConfigurationForm(forms.ModelForm):
    class Meta:
        model = CheckInConfiguration
        fields = [
            "name", "description", "welcome_message", "location_name",
            "is_active", "rooms", "min_age", "max_age", "min_grade",
            "max_grade", "groups",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "rooms": forms.CheckboxSelectMultiple(),
            "groups": forms.CheckboxSelectMultiple(),
        }


class CheckInWindowForm(forms.ModelForm):
    class Meta:
        model = CheckInWindow
        fields = [
            "schedule_type", "day_of_week", "specific_date",
            "checkin_opens", "event_starts", "checkin_closes", "event_ends",
            "is_active", "notes",
        ]
        widgets = {
            "specific_date": forms.DateInput(attrs={"type": "date"}),
            "checkin_opens": forms.TimeInput(attrs={"type": "time"}),
            "event_starts": forms.TimeInput(attrs={"type": "time"}),
            "checkin_closes": forms.TimeInput(attrs={"type": "time"}),
            "event_ends": forms.TimeInput(attrs={"type": "time"}),
        }


CheckInWindowFormSet = inlineformset_factory(
    CheckInConfiguration,
    CheckInWindow,
    form=CheckInWindowForm,
    extra=1,
    min_num=1,
    validate_min=True,
    can_delete=True,
)


class KioskPinForm(forms.Form):
    pin = forms.CharField(max_length=6, widget=forms.PasswordInput)

    def __init__(self, *args, expected_pin=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_pin = expected_pin

    def clean_pin(self):
        pin = self.cleaned_data["pin"]
        if self.expected_pin and pin != self.expected_pin:
            raise forms.ValidationError("Incorrect PIN.")
        return pin


class KioskLookupForm(forms.Form):
    query = forms.CharField(
        max_length=100,
        min_length=2,
        widget=forms.TextInput(attrs={
            "placeholder": "Last name or phone number",
            "autofocus": True,
            "autocomplete": "off",
        }),
    )


class FamilyMemberSelectForm(forms.Form):
    """Dynamic form for selecting family members and rooms at check-in."""

    def __init__(self, *args, members_with_eligibility=None, rooms=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.members_with_eligibility = members_with_eligibility or []
        self.has_rooms = bool(rooms)
        room_choices = [(r.pk, str(r)) for r in (rooms or [])]

        for person, eligible in self.members_with_eligibility:
            if eligible:
                self.fields[f"select_{person.pk}"] = forms.BooleanField(
                    required=False, label=str(person)
                )
                self.fields[f"room_{person.pk}"] = forms.ChoiceField(
                    choices=room_choices, required=False
                )

    def clean(self):
        cleaned = super().clean()
        # Backstop for the kiosk JS: when the session has rooms, every selected
        # member needs one. (Unselected members' rooms stay optional.)
        if self.has_rooms:
            for person, eligible in self.members_with_eligibility:
                if (
                    eligible
                    and cleaned.get(f"select_{person.pk}")
                    and not cleaned.get(f"room_{person.pk}")
                ):
                    self.add_error(
                        None, f"Please choose a room for {person.first_name}."
                    )
        return cleaned

    def get_selected(self):
        """Return list of (person_id, room_id) for selected members."""
        selected = []
        for person, eligible in self.members_with_eligibility:
            if eligible and self.cleaned_data.get(f"select_{person.pk}"):
                room_id = self.cleaned_data.get(f"room_{person.pk}")
                selected.append((person.pk, int(room_id) if room_id else None))
        return selected


class QuickRegistrationForm(forms.Form):
    parent_first_name = forms.CharField(max_length=150)
    parent_last_name = forms.CharField(max_length=150)
    parent_phone = forms.CharField(max_length=20)
    parent_email = forms.EmailField(required=False)
    phone_opt_in = forms.BooleanField(required=False)


class QuickRegistrationChildForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    birthdate = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    allergies = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    custody_flag = forms.BooleanField(required=False)
    custody_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    unauthorized_pickup = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class CheckInSessionForm(forms.ModelForm):
    class Meta:
        model = CheckInSession
        fields = [
            "configuration", "name", "date", "checkin_opens", "checkin_closes",
            "event_starts", "event_ends", "rooms", "is_active",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "checkin_opens": forms.TimeInput(attrs={"type": "time"}),
            "checkin_closes": forms.TimeInput(attrs={"type": "time"}),
            "event_starts": forms.TimeInput(attrs={"type": "time"}),
            "event_ends": forms.TimeInput(attrs={"type": "time"}),
            "rooms": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["configuration"].queryset = CheckInConfiguration.objects.filter(is_active=True)
        self.fields["configuration"].required = False
        self.fields["configuration"].empty_label = "— None (standalone session) —"


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name", "building", "capacity", "sort_order", "is_active"]


class PrinterConfigForm(forms.ModelForm):
    class Meta:
        model = PrinterConfiguration
        fields = "__all__"


class SecurityCodeLookupForm(forms.Form):
    security_code = forms.CharField(max_length=8)

    def clean_security_code(self):
        return self.cleaned_data["security_code"].upper().strip()
