from django import forms

from people.models import Person

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


class HouseholdNewPersonForm(forms.ModelForm):
    """Create a brand-new person and drop them straight into a family. Last name
    is optional — it falls back to the family's surname in the view."""

    relationship_type = forms.ChoiceField(
        choices=HouseholdMember.RelationshipType.choices,
        initial=HouseholdMember.RelationshipType.CHILD,
        label="Role in family",
    )

    class Meta:
        model = Person
        fields = ["first_name", "last_name", "birthdate", "grade", "gender", "phone", "email"]
        widgets = {"birthdate": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["last_name"].required = False


class HouseholdMembershipForm(forms.ModelForm):
    class Meta:
        model = HouseholdMember
        fields = ["household", "relationship_type"]

    def __init__(self, *args, **kwargs):
        person = kwargs.pop("person", None)
        super().__init__(*args, **kwargs)
        # Show members' names (not just the surname) so same-surname families are
        # distinguishable in the dropdown.
        self.fields["household"].label_from_instance = lambda hh: hh.selector_label()
        if person is not None:
            self.fields["household"].queryset = (
                Household.objects.exclude(memberships__person=person)
                .prefetch_related("memberships__person")
                .order_by("name")
            )
