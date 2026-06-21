from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from messaging.models import CommunicationLog

from core.permissions import staff_or_admin_required, staff_required
from households.forms import (
    HouseholdMembershipForm,
    HouseholdQuickCreateForm,
)
from households.models import Household, HouseholdMember
from .models import Person
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
def people_duplicates(request):
    """Review likely-duplicate people: records sharing a name or an email.

    Phone is intentionally NOT a signal — families share one number. Same-name
    groups may occasionally be distinct people, so this is a review aid, not an
    auto-merge."""
    people = list(
        Person.objects.all().prefetch_related("households").order_by("last_name", "first_name")
    )
    buckets = {}
    for p in people:
        buckets.setdefault(
            ("name", p.first_name.strip().lower(), p.last_name.strip().lower()), []
        ).append(p)
        if p.email:
            buckets.setdefault(("email", p.email.strip().lower()), []).append(p)

    groups, seen = [], set()
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        ids = frozenset(m.pk for m in members)
        if ids in seen:
            continue
        seen.add(ids)
        groups.append({
            "reason": "Same name" if key[0] == "name" else "Same email",
            "label": f"{members[0].first_name} {members[0].last_name}" if key[0] == "name" else key[1],
            "people": members,
        })
    groups.sort(key=lambda g: -len(g["people"]))
    return render(request, "people/duplicates.html", {
        "groups": groups,
        "people_in_groups": sum(len(g["people"]) for g in groups),
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
                    HouseholdMember.objects.create(
                        household=household,
                        person=person,
                        relationship_type=relationship_type,
                    )
                    messages.success(
                        request, f"Person added and linked to {household.name}."
                    )
                elif household_action == "new":
                    household_name = request.POST.get("new_household_name", "").strip()
                    if not household_name:
                        household_name = f"{person.last_name} Family"
                    household = Household.objects.create(
                        name=household_name, primary_adult=person
                    )
                    HouseholdMember.objects.create(
                        household=household,
                        person=person,
                        relationship_type=relationship_type,
                    )
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


@staff_or_admin_required
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
    communication_logs = (
        CommunicationLog.objects.filter(person=person)
        .select_related("recorded_by")
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

    context = {
        "person": person,
        "households": households,
        "registrations": registrations,
        "communication_logs": communication_logs,
        "existing_household_form": existing_household_form,
        "new_household_form": new_household_form,
        "guardians": guardians,
        "show_emergency": show_emergency,
    }
    return render(request, "people/people_detail.html", context)


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

    return render(request, "people/people_form.html", {"form": form})


@staff_required
def people_household_add(request, pk):
    person = get_object_or_404(Person, pk=pk)
    if request.method == "POST":
        form = HouseholdMembershipForm(request.POST, person=person)
        if form.is_valid():
            household = form.cleaned_data["household"]
            relationship_type = form.cleaned_data["relationship_type"]
            try:
                HouseholdMember.objects.create(
                    household=household,
                    person=person,
                    relationship_type=relationship_type,
                )
                messages.success(
                    request, f"{person} was linked to {household.name}."
                )
            except IntegrityError:
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
            household = form.save()
            HouseholdMember.objects.create(
                household=household,
                person=person,
                relationship_type=relationship_type,
            )
            messages.success(request, f"Created {household.name} and linked {person}.")
        else:
            messages.error(request, "Could not create family. Please check the form.")
    return redirect("people_detail", pk=pk)


@staff_required
def people_household_remove(request, pk, household_pk):
    person = get_object_or_404(Person, pk=pk)
    membership = get_object_or_404(
        HouseholdMember, person=person, household_id=household_pk
    )
    if request.method == "POST":
        membership.delete()
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

        # Create membership in target household
        try:
            HouseholdMember.objects.create(
                household=target_household,
                person=person,
                relationship_type=relationship_type,
            )
        except IntegrityError:
            messages.warning(
                request,
                f"{person} is already in {target_household.name}.",
            )
            return redirect("people_detail", pk=pk)

        # Remove from source if "move" (not "copy")
        if action == "move":
            source_membership.delete()
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
    other_households = Household.objects.exclude(pk=household_pk).order_by("name")
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
