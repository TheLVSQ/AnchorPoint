"""Who a volunteer serves with, and whose phone and email they may see (My serving).

Two lists: each of the volunteer's teams ("My teams") and who else on their team is serving
on each of their dates ("My schedule"). One rule decides contact details (`may_see_contact`):

- a **minor's** phone and email are never shown (under 18, in a school grade, or a child or
  student in a family; see `minor_ids`);
- a **team leader** sees the contact of everyone on the teams they lead;
- anyone else sees it when they share a team and the person chose "People on my teams"
  (`Person.contact_sharing`, the default) rather than "Team leaders only".

"Who's serving" only ever lists the viewer's own team that date, never other teams' rosters.
Templates get `Teammate` rows (plain strings), never Person objects, so nothing else about a
person (family, allergies, notes) can reach a volunteer's page. The emailed respond link shows
none of this.
"""
import re
from collections import defaultdict
from dataclasses import dataclass

from groups.models import GroupMembership
from households.models import HouseholdMember
from people.models import Person

from .access import led_teams
from .models import Assignment
from .requests import visible_to_volunteer
from .services import serving_memberships

_CHILD_ROLES = [HouseholdMember.RelationshipType.CHILD, HouseholdMember.RelationshipType.STUDENT]


@dataclass(frozen=True)
class Teammate:
    name: str
    positions: str
    is_leader: bool = False
    phone: str = ""
    email: str = ""

    @property
    def phone_href(self):
        return "tel:" + re.sub(r"\D", "", self.phone)


def is_minor(person, family_child_ids):
    """Treat as a minor: under 18 by birthdate, in a school grade, or a child / student in a
    family. No birthdate and none of the others = an adult."""
    return bool(person.is_minor or person.grade or person.pk in family_child_ids)


def minor_ids(people):
    """The ids of `people` whose contact is never shown (one query)."""
    people = list(people)
    child_ids = set(HouseholdMember.objects.filter(
        person_id__in=[p.pk for p in people], relationship_type__in=_CHILD_ROLES,
    ).values_list("person_id", flat=True))
    return {p.pk for p in people if is_minor(p, child_ids)}


def may_see_contact(*, viewer_team_ids, viewer_led_ids, subject_team_ids, sharing, minor):
    """May a volunteer see this person's phone and email?"""
    if minor:
        return False
    if viewer_led_ids & subject_team_ids:
        return True
    return sharing == Person.SHARE_WITH_TEAMS and bool(viewer_team_ids & subject_team_ids)


class Circle:
    """The people on `person`'s serving teams, as `user` (their login) may see them."""

    def __init__(self, user, person):
        self.person = person
        self.team_ids = set(serving_memberships(person).values_list("group_id", flat=True))
        self.led_ids = set(led_teams(user).values_list("pk", flat=True))
        self.memberships = list(
            GroupMembership.objects.filter(group_id__in=self.team_ids)
            .exclude(person=person)
            .select_related("person").prefetch_related("positions")
            .order_by("person__first_name", "person__last_name")
        )
        self._teams_of = defaultdict(set)
        self._leads = set()
        for m in self.memberships:
            self._teams_of[m.person_id].add(m.group_id)
            if m.role == "leader":
                self._leads.add((m.group_id, m.person_id))
        self._minors = minor_ids(m.person for m in self.memberships)

    def _teammate(self, subject, team_id, positions):
        visible = may_see_contact(
            viewer_team_ids=self.team_ids, viewer_led_ids=self.led_ids,
            subject_team_ids=self._teams_of[subject.pk] or {team_id},
            sharing=subject.contact_sharing, minor=subject.pk in self._minors,
        )
        return Teammate(
            name=f"{subject.first_name} {subject.last_name}".strip(),
            positions=positions,
            is_leader=(team_id, subject.pk) in self._leads,
            phone=(subject.phone or "") if visible else "",
            email=(subject.email or "") if visible else "",
        )

    def rosters(self):
        """{team id: [Teammate]} for each of the viewer's teams."""
        rosters = defaultdict(list)
        for m in self.memberships:
            positions = ", ".join(p.name for p in m.positions.all())
            rosters[m.group_id].append(self._teammate(m.person, m.group_id, positions))
        return rosters

    def crews(self, assignments):
        """{assignment id: [Teammate]}: who else on that team is serving that date (sent and
        not declined)."""
        assignments = list(assignments)
        others = list(
            visible_to_volunteer(Assignment.objects.filter(
                plan_id__in={a.plan_id for a in assignments},
                position__group_id__in=self.team_ids,
            )).exclude(status=Assignment.Status.DECLINED).exclude(person=self.person)
            .select_related("person", "position")
            .order_by("position__name", "person__first_name", "person__last_name")
        )
        # Someone still on a date after leaving the team isn't in `memberships`: check them too.
        strangers = {o.person for o in others if o.person_id not in self._teams_of}
        self._minors |= minor_ids(strangers)
        crews = {}
        for a in assignments:
            crews[a.pk] = [
                self._teammate(o.person, o.position.group_id, o.position.name)
                for o in others
                if o.plan_id == a.plan_id and o.position.group_id == a.position.group_id
            ]
        return crews
