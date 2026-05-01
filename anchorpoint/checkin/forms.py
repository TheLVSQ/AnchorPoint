from django import forms
from .models import Room, CheckInSession, CheckIn, PrinterConfiguration


class PhoneLookupForm(forms.Form):
    """Form for looking up family by phone number."""

    phone = forms.CharField(
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter phone number",
                "autocomplete": "off",
                "inputmode": "numeric",
                "pattern": "[0-9]*",
            }
        ),
    )


class CheckInForm(forms.Form):
    """Form for selecting people to check in."""

    person_ids = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )

    def __init__(self, *args, people=None, **kwargs):
        super().__init__(*args, **kwargs)
        if people:
            self.fields["person_ids"].choices = [
                (str(p.id), f"{p.first_name} {p.last_name}")
                for p in people
            ]


class RoomSelectionForm(forms.Form):
    """Form for selecting room assignments."""

    def __init__(self, *args, people=None, rooms=None, **kwargs):
        super().__init__(*args, **kwargs)
        if people and rooms:
            room_choices = [(str(r.id), r.name) for r in rooms]
            for person in people:
                self.fields[f"room_{person.id}"] = forms.ChoiceField(
                    choices=room_choices,
                    label=f"{person.first_name}'s room",
                    required=False,
                )


class CheckInSessionForm(forms.ModelForm):
    """Form for creating/editing check-in sessions."""

    class Meta:
        model = CheckInSession
        fields = [
            "name",
            "date",
            "checkin_opens",
            "checkin_closes",
            "event_starts",
            "event_ends",
            "rooms",
            "is_active",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "checkin_opens": forms.TimeInput(attrs={"type": "time"}),
            "checkin_closes": forms.TimeInput(attrs={"type": "time"}),
            "event_starts": forms.TimeInput(attrs={"type": "time"}),
            "event_ends": forms.TimeInput(attrs={"type": "time"}),
            "rooms": forms.CheckboxSelectMultiple,
        }


class RoomForm(forms.ModelForm):
    """Form for creating/editing rooms."""

    class Meta:
        model = Room
        fields = [
            "name",
            "building",
            "capacity",
            "sort_order",
            "is_active",
        ]


class PrinterConfigForm(forms.ModelForm):
    """Form for configuring printers."""

    class Meta:
        model = PrinterConfiguration
        fields = [
            "name",
            "printer_type",
            "connection_type",
            "host",
            "port",
            "is_default",
            "is_active",
        ]


class SecurityCodeLookupForm(forms.Form):
    """Form for looking up check-ins by security code (for checkout)."""

    security_code = forms.CharField(
        max_length=8,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter security code",
                "autocomplete": "off",
                "style": "text-transform: uppercase;",
            }
        ),
    )

    def clean_security_code(self):
        code = self.cleaned_data["security_code"]
        return code.upper().strip()
