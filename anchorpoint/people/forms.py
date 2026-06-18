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


class SignupImportForm(forms.Form):
    csv_file = forms.FileField(
        label="Signup CSV",
        help_text="One row per child. See docs/signup-import-template.csv for the columns.",
    )
    group = forms.CharField(
        required=False,
        label="Enroll into group (optional)",
        help_text='e.g. "VBS 2026" — created if it does not exist. Enrolls every imported child.',
    )

    MAX_BYTES = 2 * 1024 * 1024  # 2 MB — signup rosters are small

    def clean_csv_file(self):
        f = self.cleaned_data["csv_file"]
        if f.size > self.MAX_BYTES:
            raise forms.ValidationError("File too large (max 2 MB).")
        if not f.name.lower().endswith(".csv"):
            raise forms.ValidationError("Please upload a .csv file.")
        return f


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
            "photo_consent",
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
