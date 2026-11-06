from django import forms

from .models import Arrangement, Chart, MediaLink, Song


class SongForm(forms.ModelForm):
    class Meta:
        model = Song
        fields = ["title", "author", "ccli_number", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ArrangementForm(forms.ModelForm):
    class Meta:
        model = Arrangement
        fields = ["name", "key", "bpm", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, song=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.song = song or self.instance.song

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        others = Arrangement.objects.filter(song=self.song, name__iexact=name)
        if others.exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(f"{self.song} already has an arrangement called {name}.")
        return name


class ChartForm(forms.ModelForm):
    class Meta:
        model = Chart
        fields = ["label", "file"]
        labels = {"file": "PDF"}
        widgets = {"file": forms.ClearableFileInput(attrs={"accept": "application/pdf,.pdf"})}


class MediaLinkForm(forms.ModelForm):
    class Meta:
        model = MediaLink
        fields = ["label", "url"]
        widgets = {"url": forms.URLInput(attrs={"placeholder": "https://"})}
