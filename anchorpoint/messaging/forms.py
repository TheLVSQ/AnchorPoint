import os

from django import forms

from groups.models import Group
from people.models import Person

from . import outbound
from .models import Communication


class _BroadcastForm(forms.ModelForm):
    """Compose form for a broadcast to one person or a group. Consent, schedule and
    blackout rules live in the outbound communications module; this form only maps its
    Problems onto fields."""

    channel = None
    default_target = Communication.TargetType.PERSON

    target_type = forms.ChoiceField(choices=Communication.TargetType.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_type"].initial = self.default_target
        self.fields["person"].required = False
        self.fields["group"].required = False
        # Picked from a search (people.views.person_pick), never rendered as a <select>.
        self.fields["person"].queryset = Person.objects.all()
        self.fields["person"].widget = forms.HiddenInput()
        self.fields["group"].queryset = Group.objects.filter(is_active=True).order_by("name")

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        person, group = self._target(cleaned)
        if person is None and group is None:
            return cleaned  # _target already added a field error
        for problem in outbound.check_broadcast(
            self.channel, person=person, group=group,
            scheduled_for=cleaned.get("scheduled_for"),
        ):
            if problem.field in self.fields:
                self.add_error(problem.field, problem.message)
            else:
                self.add_error(None, problem.message)
        return cleaned

    def target(self):
        """(person, None) or (None, group): who the broadcast is aimed at."""
        return self._target(self.cleaned_data)

    def picked_people(self):
        """[the person already chosen] or [], so a form sent back with errors keeps it."""
        try:
            person = self.fields["person"].clean(self["person"].value())
        except forms.ValidationError:
            return []
        return [person] if person else []

    def _target(self, cleaned):
        if cleaned.get("target_type") == Communication.TargetType.GROUP:
            group = cleaned.get("group")
            if not group and "group" not in self.errors:
                self.add_error("group", "Select the group you want to contact.")
            return None, group
        person = cleaned.get("person")
        if not person and "person" not in self.errors:
            self.add_error("person", "Select a person to send this message to.")
        return person, None


class SmsBroadcastForm(_BroadcastForm):
    channel = Communication.Channel.SMS

    class Meta:
        model = Communication
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
        super().__init__(*args, **kwargs)
        self.fields["body"].required = True


class PhoneBlastForm(_BroadcastForm):
    channel = Communication.Channel.VOICE
    default_target = Communication.TargetType.GROUP

    class Meta:
        model = Communication
        fields = ["target_type", "person", "group", "title", "audio_file", "scheduled_for", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional notes"}),
            "scheduled_for": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    # Browser recordings and common uploads we accept before transcoding to MP3.
    ALLOWED_AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg", ".oga")
    MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = True
        self.fields["audio_file"].required = True

    def clean_audio_file(self):
        audio = self.cleaned_data.get("audio_file")
        if not audio:
            return audio
        if audio.size > self.MAX_AUDIO_BYTES:
            raise forms.ValidationError(
                "Audio file is too large (max 10 MB). Record a shorter message."
            )
        ext = os.path.splitext(audio.name or "")[1].lower()
        if ext not in self.ALLOWED_AUDIO_EXTENSIONS:
            raise forms.ValidationError(
                "Unsupported audio format. Upload an MP3 or WAV, or record in the browser."
            )
        return audio
