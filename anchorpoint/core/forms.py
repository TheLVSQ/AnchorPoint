from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from .models import OrganizationSettings, UserProfile


User = get_user_model()


class CreateUserForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(label="Email address")
    role = forms.ChoiceField(choices=UserProfile.Role.choices)
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        pw = cleaned.get("password")
        if pw:
            try:
                validate_password(pw)
            except DjangoValidationError as exc:
                self.add_error("password", exc)
        return cleaned


class EditUserForm(forms.ModelForm):
    role = forms.ChoiceField(choices=UserProfile.Role.choices)
    can_manage_communications = forms.BooleanField(required=False, label="Communications access")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

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
        pw = cleaned.get("new_password")
        if pw:
            try:
                validate_password(pw)
            except DjangoValidationError as exc:
                self.add_error("new_password", exc)
        return cleaned


class RoleAssignmentForm(forms.Form):
    user_id = forms.IntegerField(widget=forms.HiddenInput())
    role = forms.ChoiceField(choices=UserProfile.Role.choices, label="Role")
    can_manage_communications = forms.BooleanField(
        required=False,
        label="Can manage communications",
    )


class ProfileForm(forms.ModelForm):
    # Email is the sign-in identifier: changing it needs the current password,
    # so an unattended or hijacked session can't quietly take over the account.
    current_password = forms.CharField(
        required=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        label="Current password (required to change your email)",
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Last name"}),
            "email": forms.EmailInput(attrs={"placeholder": "your@email.com"}),
        }

    def clean(self):
        cleaned = super().clean()
        new_email = (cleaned.get("email") or "").strip().lower()
        old_email = (User.objects.filter(pk=self.instance.pk)
                     .values_list("email", flat=True).first() or "").lower()
        if self.instance.pk and new_email and new_email != old_email:
            if not self.instance.check_password(cleaned.get("current_password") or ""):
                self.add_error("current_password", "Enter your current password to change your email.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if user.email:
            user.username = user.email  # keep the login identifier in sync (as user_edit does)
        if commit:
            user.save()
        return user


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
            "family_alert_recipients",
        ]
        widgets = {
            "twilio_account_sid": forms.TextInput(attrs={"placeholder": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}),
            "twilio_auth_token": forms.TextInput(attrs={"placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}),
            "twilio_phone_number": forms.TextInput(attrs={"placeholder": "+15551234567"}),
            "phone_number": forms.TextInput(attrs={"placeholder": "+15551234567"}),
            "sms_blackout_start": forms.TimeInput(attrs={"type": "time"}),
            "sms_blackout_end": forms.TimeInput(attrs={"type": "time"}),
            "family_alert_recipients": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model
        # Only active staff/admins can receive family-safety alerts.
        self.fields["family_alert_recipients"].queryset = (
            get_user_model().objects.filter(
                is_active=True, profile__role__in=["admin", "staff"]
            ).order_by("first_name", "last_name", "username")
        )
        self.fields["family_alert_recipients"].label_from_instance = (
            lambda u: f"{u.get_full_name() or u.username} ({u.email or 'no email'})"
        )

