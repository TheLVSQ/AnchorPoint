from django import forms
from .models import Person

US_STATES = [
    ("", "— Select state —"),
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"),
    ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
    ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
    ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
    ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
    ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"),
    ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"),
    ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
    ("WI", "Wisconsin"), ("WY", "Wyoming"), ("DC", "District of Columbia"),
]


class PersonForm(forms.ModelForm):
    state = forms.ChoiceField(
        choices=US_STATES,
        required=False,
        widget=forms.Select,
    )

    class Meta:
        model = Person
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "phone_opt_in",
            "birthdate",
            "gender",
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
