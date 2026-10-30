"""What a person serves on, shared by the person page and "My serving"."""
from groups.models import Group, GroupMembership


def serving_memberships(person):
    """The teams `person` can be scheduled on, with their positions."""
    return (
        GroupMembership.objects.filter(person=person, group__is_active=True)
        .exclude(group__category__in=Group.NOT_SCHEDULABLE)
        .select_related("group").prefetch_related("positions")
        .order_by("group__name")
    )


def current_blockouts(person):
    return [b for b in person.blockouts.all() if b.is_current()]
