from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.permissions import staff_required
from people.models import Person

from .forms import BlockoutForm, ServingWeeksForm
from .models import Blockout
from .services import current_blockouts, serving_memberships


def _own_person(user):
    """The Person this login belongs to, or None (e.g. a staff login with no linked person)."""
    profile = getattr(user, "profile", None)
    return profile.person if profile and profile.person_id else None


# ---------------------------------------------------------------------------
# "My serving": a volunteer's own teams, weeks and blockouts
# ---------------------------------------------------------------------------

@login_required
def my_serving(request, blockout_form=None, weeks_form=None):
    person = _own_person(request.user)
    teams = []
    if person:
        for membership in serving_memberships(person):
            form = weeks_form if weeks_form and weeks_form.instance.pk == membership.pk else None
            teams.append((membership, form or ServingWeeksForm(
                instance=membership, prefix=f"m{membership.pk}")))
    return render(request, "scheduling/my_serving.html", {
        "person": person,
        "teams": teams,
        "blockouts": current_blockouts(person) if person else [],
        "blockout_form": blockout_form or (BlockoutForm(person=person) if person else None),
    })


def _own_membership(request, mid):
    person = _own_person(request.user)
    if not person:
        raise Http404
    return get_object_or_404(serving_memberships(person), pk=mid)


@login_required
@require_POST
def my_serving_weeks(request, mid):
    membership = _own_membership(request, mid)
    form = ServingWeeksForm(request.POST, instance=membership, prefix=f"m{membership.pk}")
    if not form.is_valid():
        return my_serving(request, weeks_form=form)
    form.save()
    messages.success(request, f"Saved: you serve {membership.serving_weeks_label.lower()} "
                              f"on {membership.group}.")
    return redirect("scheduling:my_serving")


@login_required
@require_POST
def my_blockout_add(request):
    person = _own_person(request.user)
    if not person:
        raise Http404
    form = BlockoutForm(request.POST, person=person)
    if not form.is_valid():
        return my_serving(request, blockout_form=form)
    blockout = form.save()
    messages.success(request, f"Blocked out {blockout.label}.")
    return redirect("scheduling:my_serving")


@login_required
@require_POST
def my_blockout_delete(request, pk):
    person = _own_person(request.user)
    if not person:
        raise Http404
    blockout = get_object_or_404(Blockout, pk=pk, person=person)
    blockout.delete()
    messages.success(request, f"Removed the blockout for {blockout.label}.")
    return redirect("scheduling:my_serving")


# ---------------------------------------------------------------------------
# Staff: blockouts on a person's page
# ---------------------------------------------------------------------------

@staff_required
@require_POST
def person_blockout_add(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    form = BlockoutForm(request.POST, person=person)
    if form.is_valid():
        blockout = form.save()
        messages.success(request, f"Blocked out {blockout.label} for {person.first_name}.")
    else:
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f"Blockout not saved: {errors}")
    return redirect("people_detail", pk=person.pk)


@staff_required
@require_POST
def person_blockout_delete(request, person_id, pk):
    blockout = get_object_or_404(Blockout, pk=pk, person_id=person_id)
    blockout.delete()
    messages.success(request, f"Removed the blockout for {blockout.label}.")
    return redirect("people_detail", pk=person_id)
