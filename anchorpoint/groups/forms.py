from django import forms

from .models import Group


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
