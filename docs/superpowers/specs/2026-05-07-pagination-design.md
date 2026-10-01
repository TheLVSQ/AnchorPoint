# Pagination — Design Spec

## Overview

Add 25-per-page pagination to the People list and Groups list views. Uses Django's built-in `Paginator` class. A shared partial template renders the controls so there's no duplicated HTML.

## Scope

- **People list** (`/people/`) — paginated, search query preserved across pages
- **Groups list** (`/groups/`) — paginated
- All other list views (events, check-in sessions) are already naturally scoped and do not need pagination

## Architecture

Each view wraps its queryset in `Paginator(queryset, 25)`, retrieves the requested page via `request.GET.get("page")`, and passes the `page_obj` to the template. The template includes a shared partial for the controls.

Page number is a `?page=N` query parameter. For the people list, search is `?q=smith` — both params coexist: `?q=smith&page=2`. The pagination partial preserves all existing query parameters when building prev/next URLs so search is never lost on page navigation.

## Views

### `people_list`

```python
from django.core.paginator import Paginator

paginator = Paginator(people, 25)
page_obj = paginator.get_page(request.GET.get("page"))
```

Context: `{"page_obj": page_obj, "query": query}`

Template iterates over `page_obj` (not `people`).

### `group_list`

```python
paginator = Paginator(groups, 25)
page_obj = paginator.get_page(request.GET.get("page"))
```

Context: adds `"page_obj": page_obj` alongside existing context keys.

Template iterates over `page_obj` (not `groups`).

## Pagination Partial

**Path:** `anchorpoint/templates/partials/pagination.html`

Rendered when `page_obj.paginator.num_pages > 1`.

Displays:
- Previous button — disabled (greyed, no href) on page 1
- "Page N of M" label
- Next button — disabled on last page

Preserves existing query params by building URLs from `request.GET` with `page` overridden. Uses a template tag approach: the partial receives `page_obj` and `request` via context (request is available globally via the `request` context processor already in settings).

Previous URL: `?page={{ page_obj.previous_page_number }}&q={{ query }}` — but to avoid hardcoding `q`, the partial uses a simple loop over `request.GET` items excluding `page`.

## URL construction in partial

```html
{% for key, value in request.GET.items %}
    {% if key != "page" %}&{{ key }}={{ value }}{% endif %}
{% endfor %}
```

This preserves any query params (search, filters) automatically without the partial needing to know about them.

## Files Changed

| File | Change |
|------|--------|
| `anchorpoint/people/views.py` | Wrap queryset in `Paginator(qs, 25)`, pass `page_obj` to context |
| `anchorpoint/groups/views.py` | Same |
| `anchorpoint/people/templates/people/people_list.html` | Iterate `page_obj`, include pagination partial |
| `anchorpoint/groups/templates/groups/group_list.html` | Iterate `page_obj`, include pagination partial |
| `anchorpoint/templates/partials/pagination.html` | New shared partial |

No migrations required.

## Testing

- People list page 1 returns 25 items when >25 exist
- People list page 2 returns correct offset
- Search + page param coexist correctly
- Groups list page 1 returns 25 items when >25 exist
- Invalid page number (e.g. `?page=999`) returns last page (Django's `get_page` handles this)
- No pagination controls when ≤25 items
