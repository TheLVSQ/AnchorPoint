from django import forms
from .models import Person


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "phone_opt_in",
            "birthdate",
            "grade",
            "marital_status",
            "profile_photo",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "salvation_date",
            "baptism_date",
            "first_visit_date",
            "allergies",
            "security_notes",
            "status",
            "notes",
        ]
        widgets = {
            "birthdate": forms.DateInput(attrs={"type": "date"}),
            "salvation_date": forms.DateInput(attrs={"type": "date"}),
            "baptism_date": forms.DateInput(attrs={"type": "date"}),
            "first_visit_date": forms.DateInput(attrs={"type": "date"}),
            "profile_photo": forms.ClearableFileInput(),
        }
