from django import forms

from groups.forms import ServingWeeksField
from groups.models import GroupMembership

from .models import Blockout


class BlockoutForm(forms.ModelForm):
    class Meta:
        model = Blockout
        fields = ["starts_on", "ends_on", "repeats_yearly", "note"]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
            "note": forms.TextInput(attrs={"placeholder": "e.g. Vacation (optional)"}),
        }
        help_texts = {"ends_on": "Leave blank for a single day."}

    def __init__(self, *args, person, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.person = person
        self.fields["ends_on"].required = False

    def clean(self):
        data = super().clean()
        if data.get("starts_on") and not data.get("ends_on"):
            data["ends_on"] = data["starts_on"]
            self.instance.ends_on = data["starts_on"]
        return data


class ServingWeeksForm(forms.ModelForm):
    """A volunteer setting their own weeks on one team (positions stay staff-only)."""

    serving_weeks = ServingWeeksField(error_messages={
        "required": "Tick at least one week, or ask a leader to take you off the team.",
    })

    class Meta:
        model = GroupMembership
        fields = ["serving_weeks"]
