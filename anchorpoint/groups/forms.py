from django import forms

from .models import WEEK_LABELS, Group, GroupMembership, Position


class GroupForm(forms.ModelForm):
    is_active = forms.TypedChoiceField(
        label="Status",
        choices=[("True", "Active"), ("False", "Archived")],
        coerce=lambda x: x == "True",
        widget=forms.Select,
    )

    class Meta:
        model = Group
        fields = [
            "name",
            "short_code",
            "category",
            "description",
            "location",
            "meeting_schedule",
            "capacity",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class ServingWeeksField(forms.MultipleChoiceField):
    """"Which weeks?" checkboxes, stored as a digit string ("13" = 1st and 3rd)."""

    widget = forms.CheckboxSelectMultiple

    def __init__(self, **kwargs):
        kwargs.setdefault("label", "Serves on")
        kwargs.setdefault("help_text", "Weeks of the month, e.g. tick only 3rd for the 3rd Sunday.")
        super().__init__(choices=list(WEEK_LABELS.items()), **kwargs)

    def prepare_value(self, value):
        return list(value) if isinstance(value, str) else value

    def clean(self, value):
        return "".join(sorted(super().clean(value)))


class MembershipForm(forms.ModelForm):
    """Staff edit of one person on one team: role, positions, serving weeks."""

    serving_weeks = ServingWeeksField(
        error_messages={"required": "Tick at least one week."},
    )

    class Meta:
        model = GroupMembership
        fields = ["role", "positions", "serving_weeks"]
        widgets = {"positions": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.group.is_schedulable:  # e.g. a check-in classroom: role only
            del self.fields["positions"], self.fields["serving_weeks"]
            return
        self.fields["positions"].queryset = self.instance.group.positions.all()
        self.fields["positions"].help_text = "The positions this person can be scheduled into."


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ["name"]
        labels = {"name": "New position"}
        widgets = {"name": forms.TextInput(attrs={"placeholder": "e.g. Keys, Vocals, Sound"})}

    def __init__(self, *args, group, **kwargs):
        super().__init__(*args, **kwargs)
        self.group = group

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.group.positions.filter(name__iexact=name).exists():
            raise forms.ValidationError(f"{self.group} already has {name}.")
        return name

    def save(self, commit=True):
        self.instance.group = self.group
        return super().save(commit)
