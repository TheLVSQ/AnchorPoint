from django import forms

from groups.forms import ServingWeeksField
from groups.models import Group, GroupMembership, Position

from .models import Blockout, Plan, ServiceType, ServiceTypeNeed
from .schedule import MAX_RANGE_DAYS


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


class ServiceTypeForm(forms.ModelForm):
    """A service type plus how many of each position it needs: one number box per position on
    every schedulable team (0 = not needed)."""

    class Meta:
        model = ServiceType
        fields = ["name", "weekday", "default_time", "is_active"]
        widgets = {"default_time": forms.TimeInput(attrs={"type": "time"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["weekday"].choices = [("", "Every day (e.g. VBS)")] + ServiceType.WEEKDAYS
        counts = {}
        if self.instance.pk:
            counts = dict(self.instance.needs.values_list("position_id", "count"))
        self.teams = []
        positions = (Position.objects.filter(group__is_active=True)
                     .exclude(group__category__in=Group.NOT_SCHEDULABLE)
                     .select_related("group").order_by("group__name", "name"))
        for position in positions:
            name = f"need_{position.pk}"
            self.fields[name] = forms.IntegerField(
                label=position.name, min_value=0, max_value=50, required=False,
                initial=counts.get(position.pk, 0),
                widget=forms.NumberInput(attrs={"class": "need-input"}),
            )
            if not self.teams or self.teams[-1][0] != position.group:
                self.teams.append((position.group, []))
            self.teams[-1][1].append(self[name])

    def save(self, commit=True):
        service_type = super().save()
        for name, value in self.cleaned_data.items():
            if not name.startswith("need_"):
                continue
            position_id = int(name.removeprefix("need_"))
            if value:
                ServiceTypeNeed.objects.update_or_create(
                    service_type=service_type, position_id=position_id,
                    defaults={"count": value})
            else:
                ServiceTypeNeed.objects.filter(
                    service_type=service_type, position_id=position_id).delete()
        return service_type


class AddDatesForm(forms.Form):
    starts_on = forms.DateField(label="From", widget=forms.DateInput(attrs={"type": "date"}))
    ends_on = forms.DateField(label="To", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        start, end = data.get("starts_on"), data.get("ends_on")
        if start and end:
            if end < start:
                raise forms.ValidationError("The end date can't be before the start date.")
            if (end - start).days > MAX_RANGE_DAYS:
                raise forms.ValidationError("Add up to a year of dates at a time.")
        return data


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["title", "time", "notes"]
        widgets = {
            "time": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
