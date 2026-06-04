# Live People Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live HTMX search endpoint and partial template so the People list updates instantly as the user types, without a page reload.

**Architecture:** A new `people_search` view returns only a results partial (no base template). The existing `people_list.html` extracts its results loop into that partial and adds HTMX attributes to the search input. The full page `?q=` GET form continues to work unchanged.

**Tech Stack:** Django 5.2, HTMX (existing), Django Paginator (existing)

**Design Spec:** `docs/superpowers/specs/2026-05-07-live-people-search-design.md`

---

## File Structure

### New Files
- `anchorpoint/people/templates/people/partials/people_results.html` — extracted results loop, wrapped in `<div id="people-results">`

### Modified Files
- `anchorpoint/people/views.py` — add `people_search` view
- `anchorpoint/people/urls.py` — add `search/` URL
- `anchorpoint/people/templates/people/people_list.html` — add HTMX attrs to input, use `{% include %}` for results
- `anchorpoint/people/tests.py` — add `PeopleSearchViewTests`

---

## Task 1: `people_search` View + URL + Tests

**Files:**
- Modify: `anchorpoint/people/views.py`
- Modify: `anchorpoint/people/urls.py`
- Modify: `anchorpoint/people/tests.py`

- [ ] **Step 1: Write the failing tests**

Add to `anchorpoint/people/tests.py` (after existing imports and classes):

```python
from core.models import UserProfile


class PeopleSearchViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="searcher", password="pw")
        self.user.profile.role = UserProfile.Role.STAFF
        self.user.profile.save()
        self.client.force_login(self.user)

        Person.objects.create(first_name="Alice", last_name="Smith", phone="+15550001111")
        Person.objects.create(first_name="Bob", last_name="Smith", phone="+15550002222")
        Person.objects.create(first_name="Carol", last_name="Jones", phone="+15550003333")

    def test_search_returns_200(self):
        response = self.client.get(reverse("people_search"), {"q": "Smith"})
        self.assertEqual(response.status_code, 200)

    def test_search_filters_by_first_name(self):
        response = self.client.get(reverse("people_search"), {"q": "Alice"})
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Bob")

    def test_search_filters_by_last_name(self):
        response = self.client.get(reverse("people_search"), {"q": "Jones"})
        self.assertContains(response, "Carol")
        self.assertNotContains(response, "Alice")

    def test_search_empty_query_returns_all(self):
        response = self.client.get(reverse("people_search"), {"q": ""})
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")
        self.assertContains(response, "Carol")

    def test_search_returns_partial_with_results_div(self):
        response = self.client.get(reverse("people_search"), {"q": "Smith"})
        self.assertContains(response, 'id="people-results"')

    def test_search_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("people_search"), {"q": "Alice"})
        self.assertNotEqual(response.status_code, 200)

    def test_search_no_results_shows_empty_state(self):
        response = self.client.get(reverse("people_search"), {"q": "Zzznobody"})
        self.assertContains(response, "No people found")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test people.tests.PeopleSearchViewTests -v2
```
Expected: FAIL — `NoReverseMatch: Reverse for 'people_search' not found`

- [ ] **Step 3: Add `people_search` view to `people/views.py`**

Add these imports at the top if not already present:

```python
from django.core.paginator import Paginator
from django.db.models import Q
```

Add the following view at the end of `anchorpoint/people/views.py`:

```python
@staff_required
def people_search(request):
    """HTMX endpoint: returns the people results partial for live search."""
    query = request.GET.get("q", "").strip()
    if query:
        people = Person.objects.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query)
        ).order_by("last_name", "first_name")
    else:
        people = Person.objects.all().order_by("last_name", "first_name")

    page_obj = Paginator(people, 25).get_page(request.GET.get("page"))
    return render(request, "people/partials/people_results.html", {
        "page_obj": page_obj,
        "query": query,
    })
```

- [ ] **Step 4: Add URL to `people/urls.py`**

Add after `path("lookup/", ...)`:

```python
path("search/", views.people_search, name="people_search"),
```

Full updated `urlpatterns`:

```python
urlpatterns = [
    path("", views.people_list, name="people_list"),
    path("add/", views.people_add, name="people_add"),
    path("lookup/", views.people_lookup, name="people_lookup"),
    path("search/", views.people_search, name="people_search"),
    path("<int:pk>/", views.people_detail, name="people_detail"),
    path("<int:pk>/edit/", views.people_edit, name="people_edit"),
    path(
        "<int:pk>/households/add/",
        views.people_household_add,
        name="people_household_add",
    ),
    path(
        "<int:pk>/households/create/",
        views.people_household_create,
        name="people_household_create",
    ),
    path(
        "<int:pk>/households/<int:household_pk>/remove/",
        views.people_household_remove,
        name="people_household_remove",
    ),
]
```

- [ ] **Step 5: Create the results partial**

Create directory `anchorpoint/people/templates/people/partials/` and create `people_results.html`:

```html
<div id="people-results">
    <div class="cards">
        {% for person in page_obj %}
            <div class="card">
                <h2>{{ person.first_name }} {{ person.last_name }}</h2>
                <p>{{ person.email }}</p>
                <a href="{% url 'people_detail' person.pk %}">View</a>
            </div>
        {% empty %}
            <p>No people found.</p>
        {% endfor %}
    </div>
    {% include "partials/pagination.html" %}
</div>
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test people.tests.PeopleSearchViewTests -v2
```
Expected: All 7 tests PASS

- [ ] **Step 7: Run system check**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Commit**

```bash
git add anchorpoint/people/views.py anchorpoint/people/urls.py anchorpoint/people/templates/people/partials/people_results.html anchorpoint/people/tests.py
git commit -m "feat: add people_search HTMX endpoint and results partial"
```

---

## Task 2: Wire HTMX into the People List Page

**Files:**
- Modify: `anchorpoint/people/templates/people/people_list.html`

- [ ] **Step 1: Replace `people_list.html` with the HTMX-wired version**

Replace the full contents of `anchorpoint/people/templates/people/people_list.html`:

```html
{% extends "base.html" %}
{% block content %}

<h1>People</h1>

<form method="GET" style="margin-bottom: 20px;">
    <input type="text"
           name="q"
           placeholder="Search..."
           value="{{ query }}"
           autocomplete="off"
           hx-get="{% url 'people_search' %}"
           hx-trigger="keyup changed delay:300ms"
           hx-target="#people-results"
           hx-swap="outerHTML">
    <button type="submit">Search</button>
    <a href="{% url 'people_add' %}" style="margin-left: 10px;">Add Person</a>
</form>

{% include "people/partials/people_results.html" %}

{% endblock %}
```

- [ ] **Step 2: Verify the full page still works**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Run full people test suite**

```bash
cd anchorpoint && SECRET_KEY=devsecret DB_HOST=localhost ../venv/Scripts/python.exe manage.py test people -v2
```
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add anchorpoint/people/templates/people/people_list.html
git commit -m "feat: add live HTMX search to people list page

Typing in the search box now updates results instantly (300ms debounce)
without a page reload. GET form submit still works unchanged."
```
