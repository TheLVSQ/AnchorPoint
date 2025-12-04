from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render

from .forms import GroupForm
from .models import Group


@login_required
def group_list(request):
    groups = Group.objects.all()
    category_counts = (
        groups.values("category")
        .order_by()
        .annotate(total=Count("id"))
    )
    counts_by_category = {item["category"]: item["total"] for item in category_counts}
    category_summary = [
        {
            "key": key,
            "label": label,
            "count": counts_by_category.get(key, 0),
        }
        for key, label in Group.CATEGORY_CHOICES
    ]

    active_category_count = sum(1 for item in category_summary if item["count"] > 0)

    context = {
        "groups": groups,
        "group_count": groups.count(),
        "category_summary": category_summary,
        "active_category_count": active_category_count,
    }
    return render(request, "groups/group_list.html", context)


@login_required
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

    return render(request, "groups/group_form.html", {"form": form})
