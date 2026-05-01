from people.models import Person


# Ordered list for grade comparison
GRADE_ORDER = [
    "pre-k", "k", "1", "2", "3", "4", "5", "6",
    "7", "8", "9", "10", "11", "12",
]


def _grade_index(grade):
    """Return numeric index for grade comparison, or -1 if unknown."""
    try:
        return GRADE_ORDER.index(grade)
    except ValueError:
        return -1


def is_person_eligible(person, config):
    """
    Check if a person is eligible for a check-in configuration.

    All filters are optional. If none are set, everyone is eligible.
    When filters are set, OR logic applies — matching ANY filter qualifies.
    """
    has_age = config.min_age is not None or config.max_age is not None
    has_grade = bool(config.min_grade) or bool(config.max_grade)
    has_groups = config.groups.exists()

    if not has_age and not has_grade and not has_groups:
        return True

    if has_age and person.age is not None:
        min_ok = config.min_age is None or person.age >= config.min_age
        max_ok = config.max_age is None or person.age <= config.max_age
        if min_ok and max_ok:
            return True

    if has_grade and person.grade:
        person_idx = _grade_index(person.grade)
        min_idx = _grade_index(config.min_grade) if config.min_grade else 0
        max_idx = _grade_index(config.max_grade) if config.max_grade else len(GRADE_ORDER) - 1
        if person_idx >= 0 and min_idx <= person_idx <= max_idx:
            return True

    if has_groups:
        if person.group_memberships.filter(group__in=config.groups.all()).exists():
            return True

    return False


def get_eligible_members(household, config):
    """Return list of (person, eligible) tuples for all household members."""
    members = household.members.all().select_related()
    results = []
    for person in members:
        results.append((person, is_person_eligible(person, config)))
    return results
