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


@staff_required
def report_detail(request, slug):
    report = get_report(slug)
    if report is None:
        raise Http404("Unknown report")

    form = _bound_form(report, request)
    columns = report.columns()
    keys = [key for key, _header in columns]
    table_rows = None
    row_count = 0
    truncated = False
    if form is None or (form.is_bound and form.is_valid()):
        params = form.cleaned_data if form else {}
        all_rows = list(report.get_rows(params))
        row_count = len(all_rows)
        truncated = row_count > PREVIEW_LIMIT
        # Flatten to ordered cells so the template needs no dict-by-key lookup.
        table_rows = [
            [row.get(k, "") for k in keys] for row in all_rows[:PREVIEW_LIMIT]
        ]

    return render(request, "reporting/detail.html", {
        "report": report,
        "form": form,
        "headers": [header for _key, header in columns],
        "table_rows": table_rows,
        "row_count": row_count,
        "truncated": truncated,
        "preview_limit": PREVIEW_LIMIT,
        "export_qs": request.GET.urlencode(),
    })


@staff_required
def report_export(request, slug):
    report = get_report(slug)
    if report is None:
        raise Http404("Unknown report")

    form = _bound_form(report, request)
    if form is not None and not (form.is_bound and form.is_valid()):
        # Can't export without valid params — bounce back to the configure page.
        raise Http404("Report parameters required")
    params = form.cleaned_data if form else {}

    columns = report.columns()
    stamp = timezone.localdate().isoformat()
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{slug}-{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow([header for _key, header in columns])
    for row in report.get_rows(params):
        writer.writerow([row.get(key, "") for key, _header in columns])
    return response
