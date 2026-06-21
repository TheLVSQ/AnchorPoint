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


def is_person_eligible(person, config, config_group_ids=None):
    """
    Check if a person is eligible for a check-in configuration.

    All filters are optional. If none are set, everyone is eligible.
    When filters are set, OR logic applies — matching ANY filter qualifies.

    Pass config_group_ids (a set of group PKs) to avoid repeated DB queries
    when checking multiple people. If not provided, it's fetched from config.
    """
    has_age = config.min_age is not None or config.max_age is not None
    has_grade = bool(config.min_grade) or bool(config.max_grade)
    # Compute group IDs if not pre-fetched by caller
    if config_group_ids is None:
        config_group_ids = set(config.groups.values_list("id", flat=True))
    has_groups = len(config_group_ids) > 0

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
        # Use prefetched group memberships if available to avoid N+1 queries
        person_group_ids = {
            gm.group_id for gm in person.group_memberships.all()
        }
        if person_group_ids & config_group_ids:
            return True

    return False


def room_matches(person, room):
    """True if the person's age OR grade falls inside this room's routing band.
    A room with no band set never matches (it's not an auto-route target)."""
    has_age = room.min_age is not None or room.max_age is not None
    has_grade = bool(room.min_grade) or bool(room.max_grade)
    if not has_age and not has_grade:
        return False
    if has_grade and person.grade:
        idx = _grade_index(person.grade)
        lo = _grade_index(room.min_grade) if room.min_grade else 0
        hi = _grade_index(room.max_grade) if room.max_grade else len(GRADE_ORDER) - 1
        if idx >= 0 and lo <= idx <= hi:
            return True
    if has_age and person.age is not None:
        lo_ok = room.min_age is None or person.age >= room.min_age
        hi_ok = room.max_age is None or person.age <= room.max_age
        if lo_ok and hi_ok:
            return True
    return False


def match_room(person, rooms):
    """The first room (in given order, normally sort_order) whose age/grade band
    fits this person — or None when nothing matches (volunteer picks manually)."""
    for room in rooms:
        if room_matches(person, room):
            return room
    return None


def get_eligible_members(household, config):
    """Return list of (person, eligible) tuples for all household members."""
    # Pre-fetch config group IDs once (avoids repeated DB hits per person)
    config_group_ids = set(config.groups.values_list("id", flat=True))

    # Prefetch group memberships so the eligibility check uses Python, not N queries
    members = household.members.all().select_related().prefetch_related(
        "group_memberships"
    )
    results = []
    for person in members:
        results.append((person, is_person_eligible(person, config, config_group_ids)))
    return results
