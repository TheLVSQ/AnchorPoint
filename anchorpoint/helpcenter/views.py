from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from .guides import GUIDES, get_guide, render_guide


@login_required
def guide_list(request):
    return render(request, "helpcenter/list.html", {"guides": GUIDES})


@login_required
def guide_detail(request, slug):
    guide = get_guide(slug)
    if guide is None:
        raise Http404("No such guide")
    html, toc = render_guide(guide)
    return render(request, "helpcenter/guide.html", {
        "guide": guide, "body": html, "toc": toc,
    })
