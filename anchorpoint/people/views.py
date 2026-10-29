from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from messaging.models import Delivery

from core import invites
from core.permissions import staff_or_communications_required, staff_required
from households.forms import (
    HouseholdMembershipForm,
    HouseholdQuickCreateForm,
)
from households import hygiene, membership
from households.models import CleanupFinding, Household, HouseholdMember
from .models import Person, normalize_phone
from .forms import PersonForm, RockImportForm, SignupImportForm
from .services.signup_import import SignupImportError, parse_csv, run_import
from .services import rock_import as rock

IMPORT_SESSION_KEY = "signup_import_pending"
ROCK_IMPORT_SESSION_KEY = "rock_import_pending"


@staff_required
def people_list(request):
    query = request.GET.get("q", "").strip()

    if query:
        people = (
            Person.objects.filter(
                Q(first_name__icontains=query) | Q(last_name__icontains=query)
            ).prefetch_related("households").order_by("last_name", "first_name")
        )
    else:
        people = Person.objects.all().prefetch_related("households").order_by("last_name", "first_name")

    page_obj = Paginator(people, 25).get_page(request.GET.get("page"))
    return render(request, "people/people_list.html", {
        "page_obj": page_obj,
        "query": query,
        "total_people": Person.objects.count(),
    })


@staff_required
def people_delete(request, pk):
    """Confirm + permanently delete a person (e.g. test records).

    Deleting cascades to their household memberships, group memberships,
    check-in history, and message logs; household primary-adult links are
    nulled. Irreversible."""
    person = get_object_or_404(Person, pk=pk)
    if request.method == "POST":
        name = str(person)
        person.delete()
        messages.success(request, f"Deleted {name}.")
        return redirect("people_list")
    return render(request, "people/people_confirm_delete.html", {
        "person": person,
        "households": person.households.all(),
        "checkin_count": person.checkins.count(),
        "group_count": person.group_memberships.count(),
    })


@staff_required
def people_cleanup(request):
    """Review + cull likely-inactive imported records: visitor/guest people with
    no contact info (no email, phone, or birthdate) who aren't in a household
    with anyone else. Conservative — it won't touch a contact-less parent who's
    linked to a kid (they'd be in a multi-member household). Selecting deletes
    via the shared bulk-delete confirm flow."""
    blank_email = Q(email__isnull=True) | Q(email="")
    blank_phone = Q(phone__isnull=True) | Q(phone="")
    multi_household_ids = (
        HouseholdMember.objects.values("household")
        .annotate(c=Count("id")).filter(c__gt=1).values_list("household", flat=True)
    )
    in_multi_household = HouseholdMember.objects.filter(
        household__in=multi_household_ids
    ).values_list("person_id", flat=True)
    candidates = (
        Person.objects.filter(status__in=["visitor", "guest"])
        .filter(blank_email & blank_phone & Q(birthdate__isnull=True))
        .exclude(pk__in=in_multi_household)
        .prefetch_related("households")
        .order_by("last_name", "first_name")
    )
    return render(request, "people/cleanup.html", {
        "candidates": candidates,
        "count": candidates.count(),
    })


@staff_required
@require_POST
def people_bulk_delete(request):
    """Confirm + delete several people at once (e.g. test records). Two POST
    stages: first shows a confirmation listing the selected people, then (with
    action=confirm) deletes them. Family records are kept."""
    people = Person.objects.filter(pk__in=request.POST.getlist("ids"))
    if not people.exists():
        messages.error(request, "Select at least one person to delete.")
        return redirect("people_list")
    if request.POST.get("action") == "confirm":
        count = people.count()
        people.delete()
        messages.success(request, f"Deleted {count} {'person' if count == 1 else 'people'}.")
        return redirect("people_list")
    return render(request, "people/people_bulk_confirm_delete.html", {
        "people": people.order_by("last_name", "first_name"),
        "count": people.count(),
    })


@staff_required
def people_duplicates(request):
    """Likely-duplicate people, as found by the nightly data cleanup (one set of rules:
    households/hygiene.py + people/services/identity.py). Read-only for staff; admins
    merge on the Data cleanup page, which keeps both records' safety notes."""
    findings = list(
        CleanupFinding.objects.filter(
            kind=CleanupFinding.KIND_DUPLICATE_PERSON, status=CleanupFinding.STATUS_OPEN,
        ).select_related("person_a", "person_b")
    )
    for f in findings:
        f.cards = [hygiene.person_card(f.person_a), hygiene.person_card(f.person_b)]
    return render(request, "people/duplicates.html", {
        "findings": findings,
        "last_run": hygiene.last_run(),
    })


@staff_required
def people_add(request):
    household_error = ""
    household_action = "skip"
    selected_household_id = ""

    if request.method == "POST":
        form = PersonForm(request.POST, request.FILES)
        household_action = request.POST.get("household_action", "skip")
        selected_household_id = request.POST.get("household_id", "")
        relationship_type = request.POST.get("household_relationship", "adult")

        # Validate the family choice BEFORE creating anything — a bad choice
        # used to silently produce an unlinked person with a success message.
        household = None
        if household_action == "existing":
            if selected_household_id.isdigit():
                household = Household.objects.filter(pk=selected_household_id).first()
            if household is None:
                household_error = "Choose which family to join (or pick “Skip for now”)."

        if form.is_valid() and not household_error:
            with transaction.atomic():
                person = form.save()

                if household_action == "existing":
                    membership.add_member(household, person, relationship_type)
                    messages.success(
                        request, f"Person added and linked to {household.name}."
                    )
                elif household_action == "new":
                    household = membership.create_family(
                        name=request.POST.get("new_household_name", "")
                        or f"{person.last_name} Family",
                    )
                    # Primary adult only if they joined as an adult (membership rule).
                    membership.add_member(household, person, relationship_type)
                    messages.success(
                        request,
                        f"Person added and {household.name} household created.",
                    )
                else:
                    messages.success(request, "Person added successfully!")

            return redirect("people_detail", pk=person.pk)
    else:
        form = PersonForm()

    households = Household.objects.all().order_by("name")
    return render(request, "people/people_form.html", {
        "form": form,
        "households": households,
        "household_action": household_action,
        "selected_household_id": selected_household_id,
        "household_error": household_error,
        # New person has no household yet, so no adults/address to copy from.
        "household_adults": [],
        "family_address": None,
    })


@staff_required
def signup_import(request):
    """Upload a signup CSV → review a dry-run preview → confirm to commit.

    Preview and commit run the same `run_import` service the management command
    uses. The parsed CSV text is stashed in the session between the two steps."""
    form = SignupImportForm()
    result = None
    stage = "upload"

    if request.method == "POST" and request.POST.get("action") == "commit":
        pending = request.session.get(IMPORT_SESSION_KEY)
        if not pending:
            messages.error(request, "Your import session expired — please upload the file again.")
            return redirect("signup_import")
        try:
            rows = parse_csv(pending["text"])
            result = run_import(rows, commit=True, group_name=pending.get("group", ""))
        except SignupImportError as exc:
            messages.error(request, str(exc))
            return redirect("signup_import")
        request.session.pop(IMPORT_SESSION_KEY, None)
        stage = "done"
        messages.success(request, "Import complete.")

    elif request.method == "POST":
        form = SignupImportForm(request.POST, request.FILES)
        if form.is_valid():
            raw = form.cleaned_data["csv_file"].read()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            group = form.cleaned_data["group"].strip()
            try:
                rows = parse_csv(text)
                result = run_import(rows, commit=False, group_name=group)
            except SignupImportError as exc:
                form.add_error("csv_file", str(exc))
            else:
                # Stash for the confirm step (rosters are small; capped at 2 MB).
                request.session[IMPORT_SESSION_KEY] = {"text": text, "group": group}
                stage = "preview"

    return render(request, "people/import.html", {
        "form": form,
        "result": result,
        "stage": stage,
    })


@staff_required
def rock_import_view(request):
    """Migrate another CMS's person-export CSV: upload → dry-run preview → commit.

    Shares run_rock_import with the management command. The parsed CSV text is
    stashed in the (DB-backed) session between preview and commit."""
    form = RockImportForm()
    result = None
    stage = "upload"

    if request.method == "POST" and request.POST.get("action") == "commit":
        pending = request.session.get(ROCK_IMPORT_SESSION_KEY)
        if not pending:
            messages.error(request, "Your import session expired — please upload the file again.")
            return redirect("rock_import")
        try:
            rows = rock.parse_csv(pending["text"])
            result = rock.run_rock_import(rows, commit=True)
        except rock.RockImportError as exc:
            messages.error(request, str(exc))
            return redirect("rock_import")
        request.session.pop(ROCK_IMPORT_SESSION_KEY, None)
        stage = "done"
        messages.success(request, "Rock import complete.")

    elif request.method == "POST":
        form = RockImportForm(request.POST, request.FILES)
        if form.is_valid():
            raw = form.cleaned_data["csv_file"].read()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            try:
                rows = rock.parse_csv(text)
                result = rock.run_rock_import(rows, commit=False)
            except rock.RockImportError as exc:
                form.add_error("csv_file", str(exc))
            else:
                request.session[ROCK_IMPORT_SESSION_KEY] = {"text": text}
                stage = "preview"

    return render(request, "people/rock_import.html", {
        "form": form,
        "result": result,
        "stage": stage,
    })


@staff_required
def people_detail(request, pk):
    person = get_object_or_404(Person, pk=pk)
    households = (
        person.households.all()
        .prefetch_related("memberships__person")
        .order_by("name")
    )
    registrations = (
        person.event_registrations.select_related("event", "registration")
        .order_by("-registration__created_at")
    )
    deliveries = (
        Delivery.objects.filter(person=person)
        .select_related("communication", "communication__created_by")
        .order_by("-created_at")[:10]
    )
    existing_household_form = HouseholdMembershipForm(person=person)
    new_household_form = HouseholdQuickCreateForm(initial={"primary_adult": person.pk})

    # Emergency-contact card: for a minor (or an age-unknown child member of a
    # family), surface their guardians' phone numbers up top. Guardians are the
    # adults across this person's households, primary adult first, de-duped.
    guardians = []
    seen = set()
    own_relationships = set()
    for hh in households:
        members = sorted(
            hh.memberships.all(),
            key=lambda m: m.person_id != hh.primary_adult_id,
        )
        for membership in members:
            if membership.person_id == person.pk:
                own_relationships.add(membership.relationship_type)
                continue
            if (
                membership.relationship_type == HouseholdMember.RelationshipType.ADULT
                and membership.person_id not in seen
            ):
                seen.add(membership.person_id)
                guardians.append({
                    "person": membership.person,
                    "is_primary": membership.person_id == hh.primary_adult_id,
                })
    child_relationships = {
        HouseholdMember.RelationshipType.CHILD,
        HouseholdMember.RelationshipType.STUDENT,
    }
    show_emergency = person.is_minor is True or (
        person.is_minor is None and bool(own_relationships & child_relationships)
    )

    # Key fields worth chasing when blank (shown as one quiet line instead of
    # a column of "-" placeholders). Adults: reachability; kids: safety basics.
    missing = []
    if not person.birthdate:
        missing.append("birthdate")
    if not person.formatted_address and not any(h.formatted_address for h in households):
        missing.append("address")  # a family address counts (kids rarely have their own)
    if show_emergency:
        if not person.grade:
            missing.append("grade")
    else:
        if not person.phone:
            missing.append("phone")
        if not person.email:
            missing.append("email")

    context = {
        "person": person,
        "missing_fields": missing,
        "households": households,
        "registrations": registrations,
        "deliveries": deliveries,
        "existing_household_form": existing_household_form,
        "new_household_form": new_household_form,
        "guardians": guardians,
        "show_emergency": show_emergency,
        "login_user": invites.login_for(person),
    }
    return render(request, "people/people_detail.html", context)


def _household_adults(person):
    """Adult members across this person's households (excluding the person),
    de-duped — powers the 'copy emergency contact from a family adult' helper."""
    seen, adults = set(), []
    for household in person.households.all():
        for membership in household.memberships.select_related("person").all():
            other = membership.person
            if (
                other.pk != person.pk
                and other.pk not in seen
                and membership.relationship_type == HouseholdMember.RelationshipType.ADULT
            ):
                seen.add(other.pk)
                adults.append(other)
    return adults


def _family_address(person):
    """The household's address (or a household member's, if the household record
    itself has none) to offer copying onto a person with an incomplete address.
    Returns a dict of address parts, or None when no family address is on file."""
    for household in person.households.all():
        sources = [household] + [
            m.person for m in household.memberships.all() if m.person_id != person.pk
        ]
        for src in sources:
            if getattr(src, "address_line1", None):
                return {
                    "line1": src.address_line1 or "",
                    "line2": getattr(src, "address_line2", "") or "",
                    "city": src.city or "",
                    "state": src.state or "",
                    "zip": src.postal_code or "",
                    "household": household.name,
                }
    return None


@staff_required
def people_edit(request, pk):
    person = get_object_or_404(Person, pk=pk)

    if request.method == "POST":
        form = PersonForm(request.POST, request.FILES, instance=person)
        if form.is_valid():
            form.save()
            messages.success(request, "Person updated successfully!")
            return redirect("people_detail", pk=pk)
    else:
        form = PersonForm(instance=person)

    return render(request, "people/people_form.html", {
        "form": form,
        "household_adults": _household_adults(person),
        "family_address": _family_address(person),
    })


@staff_required
def people_household_add(request, pk):
    person = get_object_or_404(Person, pk=pk)
    if request.method == "POST":
        form = HouseholdMembershipForm(request.POST, person=person)
        if form.is_valid():
            household = form.cleaned_data["household"]
            relationship_type = form.cleaned_data["relationship_type"]
            if membership.add_member(household, person, relationship_type):
                messages.success(
                    request, f"{person} was linked to {household.name}."
                )
            else:
                messages.warning(
                    request,
                    f"{person} is already part of {household.name}.",
                )
        else:
            messages.error(request, "Unable to link to family. Please fix the errors.")
    return redirect("people_detail", pk=pk)


@staff_required
def people_household_create(request, pk):
    person = get_object_or_404(Person, pk=pk)
    if request.method == "POST":
        form = HouseholdQuickCreateForm(request.POST)
        if form.is_valid():
            relationship_type = form.cleaned_data["relationship_type"]
            fields = {k: v for k, v in form.cleaned_data.items()
                      if k not in ("relationship_type", "primary_adult", "name")}
            household = membership.create_family(name=form.cleaned_data.get("name", ""), **fields)
            membership.add_member(household, person, relationship_type)
            messages.success(request, f"Created {household.name} and linked {person}.")
        else:
            messages.error(request, "Could not create family. Please check the form.")
    return redirect("people_detail", pk=pk)


@staff_required
def people_household_remove(request, pk, household_pk):
    person = get_object_or_404(Person, pk=pk)
    household_membership = get_object_or_404(
        HouseholdMember, person=person, household_id=household_pk
    )
    if request.method == "POST":
        membership.remove_member(household_membership.household, person)
        messages.success(request, "Removed from family.")
    return redirect("people_detail", pk=pk)


@staff_required
def people_household_move(request, pk, household_pk):
    """Move or copy a person from one household to another."""
    person = get_object_or_404(Person, pk=pk)
    source_membership = get_object_or_404(
        HouseholdMember, person=person, household_id=household_pk
    )

    if request.method == "POST":
        target_household_id = request.POST.get("target_household")
        action = request.POST.get("move_action", "move")  # "move" or "copy"
        relationship_type = request.POST.get(
            "relationship_type", source_membership.relationship_type
        )

        if not target_household_id:
            messages.error(request, "Please select a target household.")
            return redirect("people_detail", pk=pk)

        try:
            target_household = Household.objects.get(pk=target_household_id)
        except Household.DoesNotExist:
            messages.error(request, "Target household not found.")
            return redirect("people_detail", pk=pk)

        if relationship_type not in HouseholdMember.RelationshipType.values:
            relationship_type = source_membership.relationship_type
        if not membership.move_member(
            person, source_membership.household, target_household,
            role=relationship_type, keep_in_source=(action != "move"),
        ):
            messages.warning(
                request,
                f"{person} is already in {target_household.name}.",
            )
            return redirect("people_detail", pk=pk)

        if action == "move":
            messages.success(
                request,
                f"Moved {person} from {source_membership.household.name} "
                f"to {target_household.name}.",
            )
        else:
            messages.success(
                request,
                f"Added {person} to {target_household.name} "
                f"(kept in {source_membership.household.name}).",
            )

        return redirect("people_detail", pk=pk)

    # GET: show the move form
    other_households = (
        Household.objects.exclude(pk=household_pk)
        .prefetch_related("memberships__person")
        .order_by("name")
    )
    return render(request, "people/people_household_move.html", {
        "person": person,
        "source_membership": source_membership,
        "other_households": other_households,
        "relationship_choices": HouseholdMember.RelationshipType.choices,
    })


@staff_required
def people_lookup(request):
    query = (request.GET.get("q") or "").strip()
    results = []
    if query:
        people = (
            Person.objects.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
            )
            .order_by("last_name", "first_name")[:8]
        )
        for person in people:
            results.append(
                {
                    "id": person.pk,
                    "name": f"{person.first_name} {person.last_name}".strip(),
                    "email": person.email or "",
                    "phone": person.phone or "",
                }
            )
    return JsonResponse({"results": results})


@staff_required
def people_search(request):
    """HTMX endpoint: returns the people results partial for live search."""
    query = request.GET.get("q", "").strip()
    if query:
        people = Person.objects.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query)
        ).order_by("last_name", "first_name")
    else:
        people = Person.objects.all().prefetch_related("households").order_by("last_name", "first_name")

    page_obj = Paginator(people, 25).get_page(request.GET.get("page"))
    return render(request, "people/partials/people_results.html", {
        "page_obj": page_obj,
        "query": query,
    })


PERSON_PICK_LIMIT = 15


@staff_or_communications_required
def person_pick(request):
    """HTMX: radio list (name="person") for a form's person picker, used instead of
    a <select> of the whole directory (registration match queue, SMS compose).

    Every word must match a first name, last name or email ("kyle alt" finds Kyle Alt);
    a word with 4+ digits matches phone numbers.
    """
    words = request.GET.get("q", "").split()
    if not words:
        return HttpResponse("")
    people = Person.objects.all()
    for word in words:
        match = (
            Q(first_name__icontains=word)
            | Q(last_name__icontains=word)
            | Q(email__icontains=word)
        )
        digits = normalize_phone(word)
        if len(digits) >= 4:
            match |= Q(normalized_phone__contains=digits)
        people = people.filter(match)
    people = list(
        people.prefetch_related("households").order_by("last_name", "first_name")[
            : PERSON_PICK_LIMIT + 1
        ]
    )
    return render(
        request,
        "people/partials/person_pick_results.html",
        {
            "people": people[:PERSON_PICK_LIMIT],
            "more": len(people) > PERSON_PICK_LIMIT,
        },
    )
