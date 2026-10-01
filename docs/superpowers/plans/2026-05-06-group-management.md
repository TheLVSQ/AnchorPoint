# Group Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a group detail page with inline HTMX member management (search, add person, add whole family, remove) plus group edit and delete.

**Architecture:** Six new views added to `groups/views.py`, six new URL patterns, four new templates, and minor updates to the existing list and form templates. A `_render_member_list()` helper keeps the member list partial rendering DRY across add and remove endpoints. No model changes — `Group` and `GroupMembership` already have everything needed.

**Tech Stack:** Django 5.2, HTMX (existing), `GroupMembership` model, `Household.members` M2M

**Design Spec:** `docs/superpowers/specs/2026-05-06-group-management-design.md`

---

## File Structure

### Modified Files
- `anchorpoint/groups/views.py` — add `group_detail`, `group_edit`, `group_delete`, `group_member_search`, `group_member_add`, `group_member_remove`, `_render_member_list` helper
- `anchorpoint/groups/urls.py` — add 6 URL patterns
- `anchorpoint/groups/templates/groups/group_list.html` — make group names clickable links
- `anchorpoint/groups/templates/groups/group_form.html` — accept `cancel_url` context variable

### New Files
- `anchorpoint/groups/templates/groups/group_detail.html` — detail page with metadata, member list, add section
- `anchorpoint/groups/templates/groups/group_member_list.html` — HTMX partial: member list wrapped in `<div id="member-list">`
- `anchorpoint/groups/templates/groups/group_member_search_results.html` — HTMX partial: name search dropdown
- `anchorpoint/groups/templates/groups/group_confirm_delete.html` — delete confirmation page
- `anchorpoint/groups/tests.py` — all tests (currently empty)

---

## Task 1: Group Detail View + Clickable List

**Files:**
- Modify: `anchorpoint/groups/views.py`
- Modify: `anchorpoint/groups/urls.py`
- Create: `anchorpoint/groups/templates/groups/group_detail.html`
- Modify: `anchorpoint/groups/templates/groups/group_list.html`
- Modify: `anchorpoint/groups/tests.py`

- [ ] **Step 1: Write the failing tests**

Replace `anchorpoint/groups/tests.py` with:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from people.models import Person
from households.models import Household

from .models import Group, GroupMembership


def make_staff_user(username="staffuser"):
    User = get_user_model()
    user = User.objects.create_user(username=username, password="pw")
    user.profile.role = "staff"
    user.profile.save()
    return user


class GroupDetailViewTests(TestCase):
    def setUp(self):
        self.user = make_staff_user()
        self.client.force_login(self.user)
        self.group = Group.objects.create(
            name="Sunday Volunteers",
            category="volunteer",
            location="Main Hall",
            meeting_schedule="Sundays at 8am",
        )

    def test_detail_returns_200(self):
        response = self.client.get(reverse("groups:detail", args=[self.group.pk]))
        self.assertEqual(response.status_code, 200)

    def test_detail_shows_group_name(self):
        response = self.client.get(reverse("groups:detail", args=[self.group.pk]))
        self.assertContains(response, "Sunday Volunteers")

    def test_detail_shows_location_and_schedule(self):
        response = self.client.get(reverse("groups:detail", args=[self.group.pk]))
        self.assertContains(response, "Main Hall")
        self.assertContains(response, "Sundays at 8am")

    def test_list_links_to_detail(self):
        response = self.client.get(reverse("groups:list"))
        self.assertContains(response, reverse("groups:detail", args=[self.group.pk]))

    def test_unauthenticated_redirects(self):
        self.client.logout()
        response = self.client.get(reverse("groups:detail", args=[self.group.pk]))
        self.assertRedirects(response, f"/accounts/login/?next={reverse('groups:detail', args=[self.group.pk])}", fetch_redirect_response=False)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupDetailViewTests -v2
```
Expected: FAIL — `NoReverseMatch: Reverse for 'detail' not found`

- [ ] **Step 3: Add the `group_detail` view to `views.py`**

Add this import at the top of `anchorpoint/groups/views.py` (after existing imports):

```python
from django.shortcuts import get_object_or_404
```

Add this view at the end of `anchorpoint/groups/views.py`:

```python
@staff_required
def group_detail(request, pk):
    group = get_object_or_404(Group, pk=pk)
    return render(request, "groups/group_detail.html", {"group": group})
```

- [ ] **Step 4: Add URL pattern to `urls.py`**

Replace `anchorpoint/groups/urls.py` with:

```python
from django.urls import path

from . import views

app_name = "groups"

urlpatterns = [
    path("", views.group_list, name="list"),
    path("new/", views.group_create, name="create"),
    path("<int:pk>/", views.group_detail, name="detail"),
    path("<int:pk>/edit/", views.group_edit, name="edit"),
    path("<int:pk>/delete/", views.group_delete, name="delete"),
    path("<int:pk>/members/add/", views.group_member_add, name="member_add"),
    path("<int:pk>/members/<int:mid>/remove/", views.group_member_remove, name="member_remove"),
    path("<int:pk>/member-search/", views.group_member_search, name="member_search"),
]
```

Note: all six new URLs are added now so the reverse lookups work in templates throughout. The views for edit, delete, member_add, member_remove, member_search will be added as stubs below and replaced in later tasks.

Add these stubs at the end of `anchorpoint/groups/views.py` (after `group_detail`):

```python
@staff_required
def group_edit(request, pk):
    group = get_object_or_404(Group, pk=pk)
    return render(request, "groups/group_form.html", {"form": GroupForm(instance=group), "group": group, "cancel_url": f"/groups/{pk}/"})


@staff_required
def group_delete(request, pk):
    group = get_object_or_404(Group, pk=pk)
    return render(request, "groups/group_confirm_delete.html", {"group": group})


def _render_member_list(request, group):
    memberships = group.memberships.select_related("person").order_by(
        "person__last_name", "person__first_name"
    )
    return render(request, "groups/group_member_list.html", {
        "group": group,
        "memberships": memberships,
    })


from django.http import HttpResponse
from django.views.decorators.http import require_POST

@staff_required
def group_member_search(request, pk):
    group = get_object_or_404(Group, pk=pk)
    return HttpResponse("")


@staff_required
@require_POST
def group_member_add(request, pk):
    group = get_object_or_404(Group, pk=pk)
    return _render_member_list(request, group)


@staff_required
@require_POST
def group_member_remove(request, pk, mid):
    group = get_object_or_404(Group, pk=pk)
    return _render_member_list(request, group)
```

- [ ] **Step 5: Create `group_detail.html`**

Create `anchorpoint/groups/templates/groups/group_detail.html`:

```html
{% extends "base.html" %}
{% block content %}

<a class="ghost-link" href="{% url 'groups:list' %}">&larr; Back to Groups</a>

<div class="page-header">
    <h1>{{ group.name }}</h1>
    <p class="page-subtitle">
        <span class="chip">{{ group.get_category_display }}</span>
        {% if group.is_active %}
            <span class="chip" style="background:#dcfce7;color:#166534;">Active</span>
        {% else %}
            <span class="chip">Archived</span>
        {% endif %}
    </p>
</div>

<div class="hero-actions" style="margin-bottom:2rem;">
    <a href="{% url 'groups:edit' group.pk %}" class="btn ghost">Edit Group</a>
    <a href="{% url 'groups:delete' group.pk %}" class="btn ghost" style="color:#dc2626;">Delete</a>
</div>

{% if group.description or group.location or group.meeting_schedule or group.capacity %}
<div class="detail-card" style="margin-bottom:2rem;">
    {% if group.description %}
        <p style="margin-bottom:1rem;">{{ group.description }}</p>
    {% endif %}
    <ul class="detail-list">
        {% if group.location %}
            <li><span>Location</span><strong>{{ group.location }}</strong></li>
        {% endif %}
        {% if group.meeting_schedule %}
            <li><span>Schedule</span><strong>{{ group.meeting_schedule }}</strong></li>
        {% endif %}
        {% if group.capacity %}
            <li><span>Capacity</span><strong>{{ group.capacity }}</strong></li>
        {% endif %}
    </ul>
</div>
{% endif %}

<section class="detail-card">
    <h2>Members</h2>
    {% include "groups/group_member_list.html" %}

    <div style="margin-top:1.5rem;">
        <h3 style="margin-bottom:0.5rem;">Add Members</h3>
        <input type="text"
               name="q"
               placeholder="Search by name..."
               autocomplete="off"
               hx-get="{% url 'groups:member_search' group.pk %}"
               hx-trigger="keyup changed delay:300ms"
               hx-target="#member-search-results"
               style="width:100%;max-width:400px;">
        <div id="member-search-results" style="max-width:400px;border:1px solid var(--gray-200);border-radius:6px;margin-top:0.25rem;"></div>
    </div>
</section>

{% endblock %}
```

- [ ] **Step 6: Create `group_member_list.html` stub**

Create `anchorpoint/groups/templates/groups/group_member_list.html`:

```html
<div id="member-list">
    <div class="list-card__body">
        {% for membership in memberships %}
            <div class="list-item">
                <div>
                    <strong>
                        <a href="{% url 'people_detail' membership.person.pk %}" class="ghost-link">
                            {{ membership.person.first_name }} {{ membership.person.last_name }}
                        </a>
                    </strong>
                    <span class="chip" style="margin-left:0.5rem;">{{ membership.get_role_display }}</span>
                </div>
                <form method="post"
                      action="{% url 'groups:member_remove' group.pk membership.pk %}"
                      hx-post="{% url 'groups:member_remove' group.pk membership.pk %}"
                      hx-target="#member-list"
                      hx-swap="outerHTML">
                    {% csrf_token %}
                    <button type="submit" class="btn ghost" style="color:#dc2626;padding:0.25rem 0.75rem;">Remove</button>
                </form>
            </div>
        {% empty %}
            <p class="empty-state">No members yet. Search below to add people.</p>
        {% endfor %}
    </div>
</div>
```

Note: `group_detail` view doesn't pass `memberships` yet — that's wired up in Task 4. For now the partial renders an empty list, which is correct for the detail tests.

Update `group_detail` in `views.py` to pass memberships:

```python
@staff_required
def group_detail(request, pk):
    group = get_object_or_404(Group, pk=pk)
    memberships = group.memberships.select_related("person").order_by(
        "person__last_name", "person__first_name"
    )
    return render(request, "groups/group_detail.html", {
        "group": group,
        "memberships": memberships,
    })
```

- [ ] **Step 7: Update `group_list.html` to link group names**

In `anchorpoint/groups/templates/groups/group_list.html`, replace the group name line:

```html
                <strong>{{ group.name }}</strong>
```

with:

```html
                <strong>
                    <a href="{% url 'groups:detail' group.pk %}" class="ghost-link">{{ group.name }}</a>
                </strong>
```

And add a "View →" link on the right side of each list item. Replace:

```html
                <span class="detail-pill">{% if group.is_active %}Active{% else %}Archived{% endif %}</span>
```

with:

```html
                <div style="display:flex;align-items:center;gap:0.75rem;">
                    <span class="detail-pill">{% if group.is_active %}Active{% else %}Archived{% endif %}</span>
                    <a href="{% url 'groups:detail' group.pk %}" class="ghost-link">View &rarr;</a>
                </div>
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupDetailViewTests -v2
```
Expected: All 5 tests PASS

- [ ] **Step 9: Commit**

```bash
git add anchorpoint/groups/views.py anchorpoint/groups/urls.py anchorpoint/groups/tests.py anchorpoint/groups/templates/
git commit -m "feat: add group detail page and clickable group names in list"
```

---

## Task 2: Group Edit View

**Files:**
- Modify: `anchorpoint/groups/views.py` (replace stub)
- Modify: `anchorpoint/groups/templates/groups/group_form.html`
- Modify: `anchorpoint/groups/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/groups/tests.py`:

```python
class GroupEditViewTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("edituser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Ushers", category="volunteer")

    def test_edit_page_returns_200(self):
        response = self.client.get(reverse("groups:edit", args=[self.group.pk]))
        self.assertEqual(response.status_code, 200)

    def test_edit_page_shows_current_values(self):
        response = self.client.get(reverse("groups:edit", args=[self.group.pk]))
        self.assertContains(response, "Ushers")

    def test_edit_updates_group(self):
        response = self.client.post(reverse("groups:edit", args=[self.group.pk]), {
            "name": "Head Ushers",
            "category": "volunteer",
            "short_code": "",
            "description": "",
            "location": "",
            "meeting_schedule": "",
            "capacity": "",
            "is_active": "on",
        })
        self.assertRedirects(response, reverse("groups:detail", args=[self.group.pk]))
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Head Ushers")

    def test_edit_cancel_url_points_to_detail(self):
        response = self.client.get(reverse("groups:edit", args=[self.group.pk]))
        self.assertContains(response, reverse("groups:detail", args=[self.group.pk]))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupEditViewTests -v2
```
Expected: FAIL — edit page returns 200 but redirect test fails (stub doesn't save)

- [ ] **Step 3: Replace the `group_edit` stub in `views.py`**

Replace the `group_edit` stub with:

```python
@staff_required
def group_edit(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == "POST":
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, f"{group.name} updated.")
            return redirect("groups:detail", pk=pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = GroupForm(instance=group)
    return render(request, "groups/group_form.html", {
        "form": form,
        "group": group,
        "title": "Edit Group",
        "cancel_url": reverse("groups:detail", args=[pk]),
    })
```

Add `reverse` to the imports at the top of `views.py`:

```python
from django.urls import reverse
```

Also update `group_create` to pass `cancel_url` for consistency:

```python
@staff_required
def group_create(request):
    if request.method == "POST":
        form = GroupForm(request.POST)
        if form.is_valid():
            group = form.save()
            messages.success(request, f"{group.name} created successfully.")
            return redirect("groups:list")
        messages.error(request, "Please fix the errors below.")
    else:
        form = GroupForm()

    return render(request, "groups/group_form.html", {
        "form": form,
        "title": "Create Group",
        "cancel_url": reverse("groups:list"),
    })
```

- [ ] **Step 4: Update `group_form.html` to use `cancel_url` and `title`**

In `anchorpoint/groups/templates/groups/group_form.html`, replace:

```html
        <h1>Create Group</h1>
```

with:

```html
        <h1>{{ title }}</h1>
```

And replace the Cancel button:

```html
            <a class="btn ghost" href="{% url 'groups:list' %}">Cancel</a>
```

with:

```html
            <a class="btn ghost" href="{{ cancel_url }}">Cancel</a>
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupEditViewTests -v2
```
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/groups/views.py anchorpoint/groups/templates/groups/group_form.html anchorpoint/groups/tests.py
git commit -m "feat: add group edit view"
```

---

## Task 3: Group Delete View

**Files:**
- Modify: `anchorpoint/groups/views.py` (replace stub)
- Create: `anchorpoint/groups/templates/groups/group_confirm_delete.html`
- Modify: `anchorpoint/groups/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/groups/tests.py`:

```python
class GroupDeleteViewTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("deleteuser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Parking Team", category="volunteer")

    def test_delete_page_returns_200(self):
        response = self.client.get(reverse("groups:delete", args=[self.group.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Team")

    def test_delete_post_removes_group(self):
        pk = self.group.pk
        response = self.client.post(reverse("groups:delete", args=[pk]))
        self.assertRedirects(response, reverse("groups:list"))
        self.assertFalse(Group.objects.filter(pk=pk).exists())

    def test_delete_also_removes_memberships(self):
        person = Person.objects.create(first_name="Jane", last_name="Doe", phone="+15550001111")
        GroupMembership.objects.create(group=self.group, person=person)
        pk = self.group.pk
        self.client.post(reverse("groups:delete", args=[pk]))
        self.assertEqual(GroupMembership.objects.filter(group_id=pk).count(), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupDeleteViewTests -v2
```
Expected: FAIL — delete page renders but POST doesn't redirect or delete

- [ ] **Step 3: Replace the `group_delete` stub in `views.py`**

Replace the `group_delete` stub with:

```python
@staff_required
def group_delete(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == "POST":
        name = group.name
        group.delete()
        messages.success(request, f"{name} deleted.")
        return redirect("groups:list")
    return render(request, "groups/group_confirm_delete.html", {"group": group})
```

- [ ] **Step 4: Create `group_confirm_delete.html`**

Create `anchorpoint/groups/templates/groups/group_confirm_delete.html`:

```html
{% extends "base.html" %}
{% block content %}

<a class="ghost-link" href="{% url 'groups:detail' group.pk %}">&larr; Back to {{ group.name }}</a>

<div class="page-header">
    <h1>Delete Group</h1>
    <p class="page-subtitle">This action cannot be undone.</p>
</div>

<div class="detail-card" style="max-width:500px;">
    <p>Are you sure you want to delete <strong>{{ group.name }}</strong>?</p>
    <p class="stat-hint" style="margin-top:0.5rem;">
        {{ group.memberships.count }} member{{ group.memberships.count|pluralize }} will be removed.
    </p>

    <div class="hero-actions" style="margin-top:1.5rem;">
        <form method="post">
            {% csrf_token %}
            <button type="submit" class="btn" style="background:#dc2626;">Delete Group</button>
        </form>
        <a href="{% url 'groups:detail' group.pk %}" class="btn ghost">Cancel</a>
    </div>
</div>

{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupDeleteViewTests -v2
```
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/groups/views.py anchorpoint/groups/templates/groups/group_confirm_delete.html anchorpoint/groups/tests.py
git commit -m "feat: add group delete view with confirmation page"
```

---

## Task 4: Member Search (HTMX)

**Files:**
- Modify: `anchorpoint/groups/views.py` (replace stub)
- Create: `anchorpoint/groups/templates/groups/group_member_search_results.html`
- Modify: `anchorpoint/groups/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/groups/tests.py`:

```python
class GroupMemberSearchTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("searchuser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Worship Team", category="volunteer")
        self.alice = Person.objects.create(first_name="Alice", last_name="Smith", phone="+15550001111")
        self.bob = Person.objects.create(first_name="Bob", last_name="Smith", phone="+15550002222")
        self.carol = Person.objects.create(first_name="Carol", last_name="Jones", phone="+15550003333")
        # Bob is already a member
        GroupMembership.objects.create(group=self.group, person=self.bob)

    def _search(self, q):
        return self.client.get(
            reverse("groups:member_search", args=[self.group.pk]),
            {"q": q},
        )

    def test_empty_query_returns_empty(self):
        response = self._search("")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.strip(), b"")

    def test_search_finds_matching_people(self):
        response = self._search("Smith")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")

    def test_search_excludes_existing_members(self):
        response = self._search("Smith")
        self.assertNotContains(response, "Bob")

    def test_search_is_case_insensitive(self):
        response = self._search("alice")
        self.assertContains(response, "Alice")

    def test_search_shows_add_family_when_household_has_non_members(self):
        household = Household.objects.create(name="Smith Family")
        household.members.add(self.alice, self.carol)
        response = self._search("Alice")
        self.assertContains(response, "Add family")

    def test_search_no_add_family_when_all_in_group(self):
        household = Household.objects.create(name="Smith Solo")
        household.members.add(self.alice)
        response = self._search("Alice")
        self.assertNotContains(response, "Add family")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupMemberSearchTests -v2
```
Expected: FAIL — stub returns empty for all queries, so "finds matching people" fails

- [ ] **Step 3: Replace the `group_member_search` stub in `views.py`**

Add this import at the top of `views.py` (with existing imports):

```python
from django.db.models import Q
from people.models import Person
from households.models import Household
```

Replace the `group_member_search` stub with:

```python
@staff_required
def group_member_search(request, pk):
    group = get_object_or_404(Group, pk=pk)
    q = request.GET.get("q", "").strip()
    if not q:
        return HttpResponse("")

    existing_ids = set(group.memberships.values_list("person_id", flat=True))
    people = (
        Person.objects.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )
        .exclude(pk__in=existing_ids)
        .prefetch_related("households__members")
        [:10]
    )

    results = []
    for person in people:
        household = person.households.first()
        family_count = None
        if household:
            # Count household members not yet in the group (including this person)
            family_count = household.members.exclude(pk__in=existing_ids).count()
            if family_count <= 1:
                # Only this person would be added — no point showing "Add family"
                household = None
                family_count = None
        results.append({
            "person": person,
            "household": household,
            "family_count": family_count,
        })

    return render(request, "groups/group_member_search_results.html", {
        "group": group,
        "results": results,
    })
```

- [ ] **Step 4: Create `group_member_search_results.html`**

Create `anchorpoint/groups/templates/groups/group_member_search_results.html`:

```html
{% for result in results %}
    <div style="display:flex;justify-content:space-between;align-items:center;padding:0.5rem 0.75rem;border-bottom:1px solid var(--gray-100);">
        <span>{{ result.person.first_name }} {{ result.person.last_name }}</span>
        <div style="display:flex;gap:0.5rem;">
            <form method="post"
                  action="{% url 'groups:member_add' group.pk %}"
                  hx-post="{% url 'groups:member_add' group.pk %}"
                  hx-target="#member-list"
                  hx-swap="outerHTML">
                {% csrf_token %}
                <input type="hidden" name="person_id" value="{{ result.person.pk }}">
                <button type="submit" class="btn ghost" style="padding:0.2rem 0.6rem;font-size:0.85rem;">Add</button>
            </form>
            {% if result.household %}
                <form method="post"
                      action="{% url 'groups:member_add' group.pk %}"
                      hx-post="{% url 'groups:member_add' group.pk %}"
                      hx-target="#member-list"
                      hx-swap="outerHTML">
                    {% csrf_token %}
                    <input type="hidden" name="household_id" value="{{ result.household.pk }}">
                    <button type="submit" class="btn ghost" style="padding:0.2rem 0.6rem;font-size:0.85rem;">
                        Add family ({{ result.family_count }})
                    </button>
                </form>
            {% endif %}
        </div>
    </div>
{% empty %}
    <p style="padding:0.5rem 0.75rem;color:var(--gray-500);font-size:0.9rem;">No matching people found.</p>
{% endfor %}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupMemberSearchTests -v2
```
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add anchorpoint/groups/views.py anchorpoint/groups/templates/groups/group_member_search_results.html anchorpoint/groups/tests.py
git commit -m "feat: add HTMX member search to group detail page"
```

---

## Task 5: Member Add (Person + Household)

**Files:**
- Modify: `anchorpoint/groups/views.py` (replace stub)
- Modify: `anchorpoint/groups/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/groups/tests.py`:

```python
class GroupMemberAddTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("adduser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Greeters", category="volunteer")
        self.alice = Person.objects.create(first_name="Alice", last_name="A", phone="+15550001111")
        self.bob = Person.objects.create(first_name="Bob", last_name="B", phone="+15550002222")
        self.carol = Person.objects.create(first_name="Carol", last_name="C", phone="+15550003333")

    def _add_person(self, person):
        return self.client.post(
            reverse("groups:member_add", args=[self.group.pk]),
            {"person_id": person.pk},
        )

    def _add_household(self, household):
        return self.client.post(
            reverse("groups:member_add", args=[self.group.pk]),
            {"household_id": household.pk},
        )

    def test_add_person_creates_membership(self):
        response = self._add_person(self.alice)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(GroupMembership.objects.filter(group=self.group, person=self.alice).exists())

    def test_add_person_returns_member_list_partial(self):
        response = self._add_person(self.alice)
        self.assertContains(response, "Alice")

    def test_add_person_idempotent(self):
        self._add_person(self.alice)
        self._add_person(self.alice)
        self.assertEqual(GroupMembership.objects.filter(group=self.group, person=self.alice).count(), 1)

    def test_add_household_adds_all_non_members(self):
        household = Household.objects.create(name="A Family")
        household.members.add(self.alice, self.bob, self.carol)
        # bob is already a member
        GroupMembership.objects.create(group=self.group, person=self.bob)

        response = self._add_household(household)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(GroupMembership.objects.filter(group=self.group, person=self.alice).exists())
        self.assertTrue(GroupMembership.objects.filter(group=self.group, person=self.carol).exists())
        # Bob still has exactly 1 membership
        self.assertEqual(GroupMembership.objects.filter(group=self.group, person=self.bob).count(), 1)

    def test_add_household_returns_member_list_partial(self):
        household = Household.objects.create(name="B Family")
        household.members.add(self.alice, self.bob)
        response = self._add_household(household)
        self.assertContains(response, "member-list")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupMemberAddTests -v2
```
Expected: FAIL — stub doesn't create any memberships

- [ ] **Step 3: Replace the `group_member_add` stub in `views.py`**

Replace the `group_member_add` stub with:

```python
@staff_required
@require_POST
def group_member_add(request, pk):
    group = get_object_or_404(Group, pk=pk)
    person_id = request.POST.get("person_id")
    household_id = request.POST.get("household_id")

    if person_id:
        person = get_object_or_404(Person, pk=person_id)
        GroupMembership.objects.get_or_create(
            group=group,
            person=person,
            defaults={"role": "member"},
        )
    elif household_id:
        household = get_object_or_404(Household, pk=household_id)
        existing_ids = set(group.memberships.values_list("person_id", flat=True))
        new_memberships = [
            GroupMembership(group=group, person=person, role="member")
            for person in household.members.exclude(pk__in=existing_ids)
        ]
        GroupMembership.objects.bulk_create(new_memberships, ignore_conflicts=True)

    return _render_member_list(request, group)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupMemberAddTests -v2
```
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add anchorpoint/groups/views.py anchorpoint/groups/tests.py
git commit -m "feat: add HTMX member add (person and household) to group detail"
```

---

## Task 6: Member Remove

**Files:**
- Modify: `anchorpoint/groups/views.py` (replace stub)
- Modify: `anchorpoint/groups/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/groups/tests.py`:

```python
class GroupMemberRemoveTests(TestCase):
    def setUp(self):
        self.user = make_staff_user("removeuser")
        self.client.force_login(self.user)
        self.group = Group.objects.create(name="Media Team", category="volunteer")
        self.other_group = Group.objects.create(name="Other", category="other")
        self.person = Person.objects.create(first_name="Dave", last_name="D", phone="+15550004444")
        self.membership = GroupMembership.objects.create(group=self.group, person=self.person)

    def _remove(self, group_pk, mid):
        return self.client.post(reverse("groups:member_remove", args=[group_pk, mid]))

    def test_remove_deletes_membership(self):
        response = self._remove(self.group.pk, self.membership.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GroupMembership.objects.filter(pk=self.membership.pk).exists())

    def test_remove_returns_member_list_partial(self):
        response = self._remove(self.group.pk, self.membership.pk)
        self.assertContains(response, "member-list")

    def test_remove_wrong_group_returns_404(self):
        other_person = Person.objects.create(first_name="Eve", last_name="E", phone="+15550005555")
        other_membership = GroupMembership.objects.create(group=self.other_group, person=other_person)
        response = self._remove(self.group.pk, other_membership.pk)
        self.assertEqual(response.status_code, 404)

    def test_remove_nonexistent_membership_returns_404(self):
        response = self._remove(self.group.pk, 99999)
        self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupMemberRemoveTests -v2
```
Expected: FAIL — stub doesn't delete, wrong-group check doesn't exist

- [ ] **Step 3: Replace the `group_member_remove` stub in `views.py`**

Add `Http404` to the Django imports at the top of `views.py`:

```python
from django.http import Http404, HttpResponse
```

Replace the `group_member_remove` stub with:

```python
@staff_required
@require_POST
def group_member_remove(request, pk, mid):
    group = get_object_or_404(Group, pk=pk)
    membership = get_object_or_404(GroupMembership, pk=mid)
    if membership.group_id != group.pk:
        raise Http404("Membership does not belong to this group.")
    membership.delete()
    return _render_member_list(request, group)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups.tests.GroupMemberRemoveTests -v2
```
Expected: All 4 tests PASS

- [ ] **Step 5: Run the full groups test suite**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py test groups -v2
```
Expected: All tests PASS

- [ ] **Step 6: Run system check**

```bash
cd anchorpoint && ../venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Commit**

```bash
git add anchorpoint/groups/views.py anchorpoint/groups/tests.py
git commit -m "feat: add HTMX member remove to group detail page

Also validates membership belongs to the correct group (prevents
cross-group removal via crafted POST)."
```
