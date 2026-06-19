import csv

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.permissions import staff_required

from .reports import all_reports, get_report

PREVIEW_LIMIT = 200


@staff_required
def report_list(request):
    return render(request, "reporting/list.html", {"reports": all_reports()})


def _bound_form(report, request):
    """Return the param form bound to GET data if the report takes params."""
    if report.param_form_class is None:
        return None
    has_params = any(k in request.GET for k in report.param_form_class().fields)
    return report.param_form_class(request.GET if has_params else None)


def _selected_keys(report, request):
    """Column keys to include, in the report's declared order. Defaults to all
    when the request hasn't specified a `cols` selection."""
    all_keys = [k for k, _h in report.columns()]
    if "cols" in request.GET:
        chosen = [k for k in request.GET.getlist("cols") if k in all_keys]
        return chosen or all_keys
    return all_keys


def _sort_key_fn(value):
    """Numeric-aware sort key: numbers sort before text, no type errors."""
    s = str(value).strip()
    try:
        return (0, float(s))
    except ValueError:
        return (1, s.lower())


def _resolve(report, request, params):
    """Selected columns + rows (filtered to those columns and sorted).
    Shared by the on-screen preview and the CSV export so they always match."""
    keys = _selected_keys(report, request)
    headers = dict(report.columns())
    columns = [(k, headers[k]) for k in keys]

    rows = list(report.get_rows(params))
    sort_key = request.GET.get("sort")
    if sort_key in keys:
        rows.sort(
            key=lambda r: _sort_key_fn(r.get(sort_key, "")),
            reverse=request.GET.get("dir") == "desc",
        )
    return columns, rows


@staff_required
def report_detail(request, slug):
    report = get_report(slug)
    if report is None:
        raise Http404("Unknown report")

    form = _bound_form(report, request)
    sort_key = request.GET.get("sort")
    sort_dir = request.GET.get("dir", "asc")

    # Column picker state: every available column with its checked status.
    selected = set(_selected_keys(report, request))
    available_columns = [
        {"key": k, "header": h, "checked": k in selected}
        for k, h in report.columns()
    ]

    columns = headers = table_rows = None
    row_count = 0
    truncated = False
    if form is None or (form.is_bound and form.is_valid()):
        params = form.cleaned_data if form else {}
        columns, rows = _resolve(report, request, params)
        row_count = len(rows)
        truncated = row_count > PREVIEW_LIMIT

        # Per-column header metadata: a querystring that sorts by it (toggling
        # direction if it's already the active sort).
        headers = []
        for key, header in columns:
            qd = request.GET.copy()
            qd["sort"] = key
            qd["dir"] = "desc" if (sort_key == key and sort_dir == "asc") else "asc"
            headers.append({
                "key": key,
                "header": header,
                "sort_qs": qd.urlencode(),
                "active": sort_key == key,
                "dir": sort_dir if sort_key == key else "",
            })
        table_rows = [
            [row.get(k, "") for k, _h in columns] for row in rows[:PREVIEW_LIMIT]
        ]

    return render(request, "reporting/detail.html", {
        "report": report,
        "form": form,
        "available_columns": available_columns,
        "headers": headers,
        "table_rows": table_rows,
        "row_count": row_count,
        "truncated": truncated,
        "preview_limit": PREVIEW_LIMIT,
        "export_qs": request.GET.urlencode(),
        "no_columns": columns is not None and not columns,
    })


@staff_required
def report_export(request, slug):
    report = get_report(slug)
    if report is None:
        raise Http404("Unknown report")

    form = _bound_form(report, request)
    if form is not None and not (form.is_bound and form.is_valid()):
        raise Http404("Report parameters required")
    params = form.cleaned_data if form else {}

    columns, rows = _resolve(report, request, params)
    stamp = timezone.localdate().isoformat()
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{slug}-{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow([header for _key, header in columns])
    for row in rows:
        writer.writerow([row.get(key, "") for key, _header in columns])
    return response
