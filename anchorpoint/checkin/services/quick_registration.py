from django.db import transaction

from households.models import Household, HouseholdMember
from people.models import Person


@transaction.atomic
def register_new_family(
    parent_first,
    parent_last,
    parent_phone,
    parent_email="",
    phone_opt_in=False,
    children=None,
):
    """
    Create Person + Household records for a new family at the kiosk.

    Returns dict with keys: household, parent, children (list of Person).
    """
    children = children or []

    parent = Person.objects.create(
        first_name=parent_first,
        last_name=parent_last,
        phone=parent_phone,
        email=parent_email or None,
        phone_opt_in=phone_opt_in,
    )

    household = Household.objects.create(
        name=f"{parent_last} Family",
        phone=parent_phone,
        primary_adult=parent,
    )

    HouseholdMember.objects.create(
        household=household,
        person=parent,
        relationship_type=HouseholdMember.RelationshipType.ADULT,
    )

    child_records = []
    for child_data in children:
        child = Person.objects.create(
            first_name=child_data["first_name"],
            last_name=child_data.get("last_name", parent_last),
            birthdate=child_data.get("birthdate"),
            allergies=child_data.get("allergies", ""),
            custody_flag=child_data.get("custody_flag", False),
            custody_notes=child_data.get("custody_notes", ""),
            unauthorized_pickup=child_data.get("unauthorized_pickup", ""),
        )
        HouseholdMember.objects.create(
            household=household,
            person=child,
            relationship_type=HouseholdMember.RelationshipType.CHILD,
        )
        child_records.append(child)

    return {
        "household": household,
        "parent": parent,
        "children": child_records,
    }
