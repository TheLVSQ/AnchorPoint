from django import forms
from django.contrib.auth import get_user_model

from .models import OrganizationSettings, UserProfile


User = get_user_model()


class RoleAssignmentForm(forms.Form):
    user_id = forms.IntegerField(widget=forms.HiddenInput())
    role = forms.ChoiceField(choices=UserProfile.Role.choices, label="Role")
    can_manage_communications = forms.BooleanField(
        required=False,
        label="Can manage communications",
    )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Last name"}),
            "email": forms.EmailInput(attrs={"placeholder": "your@email.com"}),
        }


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "phone_number",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "bio",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
        }


class OrganizationSettingsForm(forms.ModelForm):
    class Meta:
        model = OrganizationSettings
        fields = [
            "name",
            "logo",
            "phone_number",
            "email",
            "website",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "twilio_account_sid",
            "twilio_auth_token",
            "twilio_phone_number",
            "sms_blackout_start",
            "sms_blackout_end",
            "kiosk_pin",
        ]
        widgets = {
            "sms_blackout_start": forms.TimeInput(attrs={"type": "time"}),
            "sms_blackout_end": forms.TimeInput(attrs={"type": "time"}),
        }
