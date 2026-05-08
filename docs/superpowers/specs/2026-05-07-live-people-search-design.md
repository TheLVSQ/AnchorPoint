# Live People Search — Design Spec

## Overview

Add HTMX-powered live search to the people list page. As the user types, results update instantly without a page reload. The existing `?q=` GET param search continues to work unchanged (progressive enhancement — no JS required for basic search).

## Architecture

The existing search input gets HTMX attributes that fire a GET request to a new `people_search` view on each keystroke (debounced 300ms). The view returns only a results partial — no base template. The full page uses `{% include %}` to render the same partial on first load.

## New View

**URL:** `GET /people/search/?q=<query>`  
**View:** `people_search` in `people/views.py`  
**Permission:** `@staff_required`  
**Template:** `people/partials/people_results.html`

Logic — identical to `people_list` queryset:
```python
@staff_required
def people_search(request):
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

Empty query returns all people (same as the unfiltered list).

## Template Changes

### `people_results.html` partial (new)

Extracted from the current `people_list.html` results loop. Renders `<div id="people-results">` containing the person cards and pagination controls.

```html
<div id="people-results">
    {% for person in page_obj %}
        <div class="card">
            <h2>{{ person.first_name }} {{ person.last_name }}</h2>
            <p>{{ person.email }}</p>
            <a href="{% url 'people_detail' person.pk %}">View</a>
        </div>
    {% empty %}
        <p>No people found.</p>
    {% endfor %}
    {% include "partials/pagination.html" %}
</div>
```

### `people_list.html` changes

1. Search input gains HTMX attributes:
```html
<input type="text" name="q" placeholder="Search..."
       value="{{ query }}"
       hx-get="{% url 'people_search' %}"
       hx-trigger="keyup changed delay:300ms"
       hx-target="#people-results"
       hx-swap="outerHTML"
       autocomplete="off">
```

2. Results area uses `{% include %}` on first load, HTMX swaps it on keyup:
```html
{% include "people/partials/people_results.html" %}
```

The existing `<form method="GET">` wrapper stays — submitting the form still works without JS.

## Pagination with Live Search

Pagination links in the partial use `?page=N&q={{ query }}` (via the shared `pagination.html` partial which preserves all GET params). Clicking a page link does a full page load — this is intentional and keeps things simple. HTMX live search resets to page 1 on each keystroke.

## Files Changed

| File | Change |
|------|--------|
| `anchorpoint/people/views.py` | Add `people_search` view |
| `anchorpoint/people/urls.py` | Add `path("search/", views.people_search, name="people_search")` |
| `anchorpoint/people/templates/people/people_list.html` | Add HTMX attrs to input, use `{% include %}` for results |
| `anchorpoint/people/templates/people/partials/people_results.html` | New partial |

No model changes. No migrations.

## Testing

- `people_search` returns 200 with results partial
- Query filters by first name and last name
- Empty query returns all people
- Unauthenticated request redirects to login
- Results partial contains `id="people-results"`
