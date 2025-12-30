from django import forms
from django.utils import timezone

from core.models import OrganizationSettings
from groups.models import Group
from people.models import Person

from .models import PhoneBlast, SmsMessage
from .services import is_within_blackout_window


class SmsMessageForm(forms.ModelForm):
    class Meta:
        model = SmsMessage
        fields = ["target_type", "person", "group", "body", "scheduled_for"]
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 4, "placeholder": "Type the SMS that will be sent"}
            ),
            "scheduled_for": forms.DateTimeInput(
                attrs={"type": "datetime-local", "placeholder": "Optional schedule"}
            ),
        }
        labels = {
            "body": "Message",
            "scheduled_for": "Schedule (optional)",
        }

    def __init__(self, *args, **kwargs):
        self.organization_settings = kwargs.pop(
            "organization_settings", OrganizationSettings.load()
        )
        super().__init__(*args, **kwargs)
        self.fields["person"].required = False
        self.fields["group"].required = False
        self.fields["person"].queryset = Person.objects.order_by(
            "last_name", "first_name"
        )
        self.fields["group"].queryset = Group.objects.filter(is_active=True).order_by(
            "name"
        )
        self._recipients = []

    def clean(self):
        cleaned = super().clean()
        target_type = cleaned.get("target_type")
        person = cleaned.get("person")
        group = cleaned.get("group")
        self._recipients = self._resolve_recipients(target_type, person, group)

        if not self._recipients and target_type:
            raise forms.ValidationError(
                "No recipients have a valid mobile number and opt-in enabled."
            )

        when = cleaned.get("scheduled_for")
        now = timezone.now()
        if when:
            if when < now:
                self.add_error("scheduled_for", "Schedule time must be in the future.")
            elif is_within_blackout_window(self.organization_settings, when):
                self.add_error(
                    "scheduled_for",
                    "This time falls inside your configured blackout window.",
                )
        else:
            if is_within_blackout_window(self.organization_settings, now):
                raise forms.ValidationError(
                    "You are inside the configured blackout window. Choose a later send time."
                )

        return cleaned

    def _resolve_recipients(self, target_type, person, group):
        recipients = []
        if target_type == SmsMessage.TargetType.PERSON:
            if not person:
                self.add_error("person", "Select a person to send this message to.")
            elif not person.phone:
                self.add_error("person", "That person does not have a phone number.")
            elif not person.phone_opt_in:
                self.add_error("person", "This person has opted out of phone contact.")
            else:
                recipients = [person]
        elif target_type == SmsMessage.TargetType.GROUP:
            if not group:
                self.add_error("group", "Select a group to broadcast your SMS.")
            else:
                members = (
                    Person.objects.filter(
                        group_memberships__group=group,
                        phone__isnull=False,
                        phone_opt_in=True,
                    )
                    .exclude(phone__exact="")
                    .distinct()
                )
                recipients = list(members)
        return recipients

    def get_recipients(self):
        return list(self._recipients)


class PhoneBlastForm(forms.ModelForm):
    class Meta:
        model = PhoneBlast
        fields = ["title", "group", "audio_file", "scheduled_for", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional notes"}),
            "scheduled_for": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        self.organization_settings = kwargs.pop(
            "organization_settings", OrganizationSettings.load()
        )
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = Group.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["group"].empty_label = None
        self._recipients = []

    def clean(self):
        cleaned = super().clean()
        group = cleaned.get("group")
        if not group:
            self.add_error("group", "Select the group you want to contact.")
        else:
            members = (
                Person.objects.filter(
                    group_memberships__group=group,
                    phone__isnull=False,
                    phone_opt_in=True,
                )
                .exclude(phone__exact="")
                .distinct()
            )
            self._recipients = list(members)

        if not self._recipients and group:
            raise forms.ValidationError(
                "Nobody in this group has a phone number with communication opt-in."
            )

        when = cleaned.get("scheduled_for")
        now = timezone.now()
        if when:
            if when < now:
                self.add_error("scheduled_for", "Schedule time must be in the future.")
            elif is_within_blackout_window(self.organization_settings, when):
                self.add_error(
                    "scheduled_for",
                    "This time falls inside your blackout window.",
                )
        else:
            if is_within_blackout_window(self.organization_settings, now):
                raise forms.ValidationError(
                    "You are inside the configured blackout window. Choose a future time."
                )

        return cleaned

    def get_recipients(self):
        return list(self._recipients)
