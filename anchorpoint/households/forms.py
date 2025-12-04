from django import forms

from .models import Household, HouseholdMember


class HouseholdForm(forms.ModelForm):
    class Meta:
        model = Household
        fields = [
            "name",
            "phone",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "primary_adult",
        ]


class HouseholdQuickCreateForm(HouseholdForm):
    relationship_type = forms.ChoiceField(
        choices=HouseholdMember.RelationshipType.choices,
        initial=HouseholdMember.RelationshipType.ADULT,
    )

    class Meta(HouseholdForm.Meta):
        fields = HouseholdForm.Meta.fields


class HouseholdMembershipForm(forms.ModelForm):
    class Meta:
        model = HouseholdMember
        fields = ["household", "relationship_type"]

    def __init__(self, *args, **kwargs):
        person = kwargs.pop("person", None)
        super().__init__(*args, **kwargs)
        if person is not None:
            self.fields["household"].queryset = Household.objects.exclude(
                memberships__person=person
            )
