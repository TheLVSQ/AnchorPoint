"""A plan's setlist: the songs on a date, in order, and who may open their charts.

Staff, and leaders of a team the plan's service type uses (`access.can_edit_setlist`), add,
reorder and remove songs on the plan page. Volunteers see the setlist for each date they serve
on My serving, and may open a chart (`songs:chart`) only while they have a sent, not declined
assignment on an upcoming plan with that song (`volunteer_can_open`). The emailed respond page
and the emails show no setlist: charts always need a login.
"""
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Max, Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from songs.models import Chart, MediaLink, Song

from .models import Assignment, PlanItem
from .requests import visible_to_volunteer

PICK_LIMIT = 10


def items(plan):
    return (plan.items.select_related("arrangement__song")
            .prefetch_related("arrangement__charts", "arrangement__links"))


def add_song(plan, arrangement):
    """Put `arrangement` at the end of `plan`'s setlist."""
    last = plan.items.aggregate(m=Max("order"))["m"]
    return PlanItem.objects.create(plan=plan, arrangement=arrangement,
                                   order=0 if last is None else last + 1)


@transaction.atomic
def move(item, step):
    """Swap `item` with its neighbour (`step` -1 = up, +1 = down). Returns False at an end."""
    ordered = list(item.plan.items.select_for_update().order_by("order", "pk"))
    index = next(i for i, other in enumerate(ordered) if other.pk == item.pk)
    target = index + step
    if not 0 <= target < len(ordered):
        return False
    ordered[index], ordered[target] = ordered[target], ordered[index]
    for position, other in enumerate(ordered):
        if other.order != position:
            other.order = position
            other.save(update_fields=["order"])
    return True


def pick(query):
    """Active songs matching `query` (title, writers or CCLI number), with their arrangements."""
    songs = Song.objects.filter(is_active=True).prefetch_related("arrangements")
    if query:
        songs = songs.filter(Q(title__icontains=query) | Q(author__icontains=query)
                             | Q(ccli_number=query))
    return list(songs[:PICK_LIMIT])


# ---------------------------------------------------------------------------
# What volunteers see
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass(frozen=True)
class SetlistSong:
    title: str
    arrangement: str
    key: str
    notes: str
    charts: list = field(default_factory=list)
    links: list = field(default_factory=list)


def for_plans(plan_ids):
    """{plan id: [SetlistSong]} for these plans (three queries, whatever the size)."""
    rows = (PlanItem.objects.filter(plan_id__in=plan_ids, kind=PlanItem.Kind.SONG)
            .select_related("arrangement__song")
            .prefetch_related(
                Prefetch("arrangement__charts", queryset=Chart.objects.order_by("label", "pk")),
                Prefetch("arrangement__links", queryset=MediaLink.objects.order_by("label", "pk")),
            ).order_by("plan_id", "order", "pk"))
    setlists = {}
    for item in rows:
        arrangement = item.arrangement
        setlists.setdefault(item.plan_id, []).append(SetlistSong(
            title=arrangement.song.title,
            arrangement="" if arrangement.name == "Default" else arrangement.name,
            key=item.display_key,
            notes=item.notes,
            charts=[Link(c.label, reverse("songs:chart", args=[c.pk]))
                    for c in arrangement.charts.all()],
            links=[Link(m.label, m.url) for m in arrangement.links.all()],
        ))
    return setlists


def volunteer_can_open(person_id, arrangement_id, today=None):
    """Does this person have a sent, not declined assignment on an upcoming plan whose
    setlist has this arrangement?"""
    if not person_id:
        return False
    today = today or timezone.localdate()
    return visible_to_volunteer(Assignment.objects.filter(
        person_id=person_id, plan__date__gte=today, plan__items__arrangement_id=arrangement_id,
    )).exclude(status=Assignment.Status.DECLINED).exists()


def plans_using(arrangement):
    """Dates an arrangement is on (why it can't be removed)."""
    return [item.plan for item in arrangement.plan_items.select_related("plan__service_type")
            .order_by("plan__date")]

