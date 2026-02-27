from django import forms
from django.contrib.auth import get_user_model

from .models import OrganizationSettings, UserProfile


User = get_user_model()


class CreateUserForm(forms.Form):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(choices=UserProfile.Role.choices)
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned


class EditUserForm(forms.ModelForm):
    role = forms.ChoiceField(choices=UserProfile.Role.choices)
    can_manage_communications = forms.BooleanField(required=False, label="Communications access")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "username"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, "profile"):
            self.fields["role"].initial = self.instance.profile.role
            self.fields["can_manage_communications"].initial = self.instance.profile.can_manage_communications


class SetPasswordForm(forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput, min_length=8, label="New password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_password") != cleaned.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned


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
