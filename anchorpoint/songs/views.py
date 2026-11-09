from django.contrib import messages
from django.db.models import ProtectedError, Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .access import can_view_chart, songs_required
from .forms import ArrangementForm, ChartForm, MediaLinkForm, SongForm
from .models import Arrangement, Chart, MediaLink, Song


@songs_required
def song_list(request):
    query = request.GET.get("q", "").strip()
    archived = request.GET.get("archived") == "1"
    songs = Song.objects.filter(is_active=not archived).prefetch_related("arrangements")
    if query:
        songs = songs.filter(Q(title__icontains=query) | Q(author__icontains=query)
                             | Q(ccli_number=query))
    return render(request, "songs/song_list.html", {
        "songs": songs, "query": query, "archived": archived,
        "archived_count": Song.objects.filter(is_active=False).count(),
    })


@songs_required
def song_form(request, pk=None):
    song = get_object_or_404(Song, pk=pk) if pk else None
    form = SongForm(request.POST or None, instance=song)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        if song:
            messages.success(request, f"Saved {saved}.")
        else:
            Arrangement.objects.create(song=saved)
            messages.success(request, f"Added {saved}. Set its key, then add a chart.")
        return redirect("songs:detail", pk=saved.pk)
    return render(request, "songs/song_form.html", {"form": form, "song": song})


@songs_required
def song_detail(request, pk, bound=None):
    """`bound` = (arrangement pk, form) to re-show a chart or link form with its errors."""
    song = get_object_or_404(Song, pk=pk)
    arrangements = []
    for arrangement in song.arrangements.prefetch_related("charts", "links"):
        chart_form = ChartForm(prefix=f"chart{arrangement.pk}")
        link_form = MediaLinkForm(prefix=f"link{arrangement.pk}")
        if bound and bound[0] == arrangement.pk:
            if isinstance(bound[1], ChartForm):
                chart_form = bound[1]
            else:
                link_form = bound[1]
        arrangements.append((arrangement, chart_form, link_form))
    return render(request, "songs/song_detail.html", {"song": song, "arrangements": arrangements})


@songs_required
@require_POST
def song_archive(request, pk):
    song = get_object_or_404(Song, pk=pk)
    song.is_active = not song.is_active
    song.save(update_fields=["is_active", "updated_at"])
    if song.is_active:
        messages.success(request, f"Restored {song} to the library.")
    else:
        messages.success(request, f"Archived {song}. It's hidden from the library; past "
                                  "setlists keep it.")
    return redirect("songs:detail", pk=song.pk)


@songs_required
def arrangement_form(request, song_pk=None, pk=None):
    arrangement = get_object_or_404(Arrangement, pk=pk) if pk else None
    song = arrangement.song if arrangement else get_object_or_404(Song, pk=song_pk)
    form = ArrangementForm(request.POST or None, instance=arrangement, song=song,
                           initial=None if arrangement else {"name": ""})
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.song = song
        saved.save()
        messages.success(request, f"Saved the {saved.name} arrangement.")
        return redirect("songs:detail", pk=song.pk)
    return render(request, "songs/arrangement_form.html", {
        "form": form, "song": song, "arrangement": arrangement,
    })


@songs_required
@require_POST
def arrangement_delete(request, pk):
    arrangement = get_object_or_404(Arrangement, pk=pk)
    song = arrangement.song
    if song.arrangements.count() == 1:
        messages.error(request, f"{song} needs at least one arrangement. Archive the song instead.")
        return redirect("songs:detail", pk=song.pk)
    try:
        arrangement.delete()  # its charts' files go too (post_delete)
    except ProtectedError:
        from django.utils import timezone

        from scheduling.setlist import plans_using
        plans = plans_using(arrangement)
        upcoming = [p for p in plans if p.date >= timezone.localdate()]
        if upcoming:
            dates = ", ".join(f"{p.date:%b %-d}" for p in upcoming[:5])
            messages.error(request, f"The {arrangement.name} arrangement is on the setlist for "
                                    f"{dates}. Take it off those dates first.")
        else:  # past setlists stay as they were (the CCLI usage report counts them)
            messages.error(request, f"The {arrangement.name} arrangement was used on past dates, "
                                    "so it stays. Archive the song if you don't use it any more.")
        return redirect("songs:detail", pk=song.pk)
    messages.success(request, f"Removed the {arrangement.name} arrangement.")
    return redirect("songs:detail", pk=song.pk)


@songs_required
@require_POST
def chart_add(request, arrangement_pk):
    arrangement = get_object_or_404(Arrangement, pk=arrangement_pk)
    form = ChartForm(request.POST, request.FILES, prefix=f"chart{arrangement.pk}")
    if not form.is_valid():
        return song_detail(request, arrangement.song_id, bound=(arrangement.pk, form))
    chart = form.save(commit=False)
    chart.arrangement = arrangement
    chart.save()
    messages.success(request, f"Added {chart.label} to {arrangement}.")
    return redirect("songs:detail", pk=arrangement.song_id)


@songs_required
@require_POST
def chart_delete(request, pk):
    chart = get_object_or_404(Chart, pk=pk)
    song_pk = chart.arrangement.song_id
    chart.delete()
    messages.success(request, f"Removed {chart.label}.")
    return redirect("songs:detail", pk=song_pk)


def chart_view(request, pk):
    """The chart PDF, for whoever may see it. Never link to `chart.file.url`."""
    if not request.user.is_authenticated:
        return redirect("login")
    chart = get_object_or_404(Chart.objects.select_related("arrangement__song"), pk=pk)
    if not can_view_chart(request.user, chart):
        return HttpResponseForbidden("You do not have permission to view this chart.")
    try:
        handle = chart.file.open("rb")
    except FileNotFoundError:
        raise Http404("This chart's file is missing. Upload it again.")
    name = slugify(f"{chart.arrangement.song.title} {chart.label}") or "chart"
    response = FileResponse(handle, content_type="application/pdf", filename=f"{name}.pdf")
    response["Content-Disposition"] = f'inline; filename="{name}.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response


@songs_required
@require_POST
def link_add(request, arrangement_pk):
    arrangement = get_object_or_404(Arrangement, pk=arrangement_pk)
    form = MediaLinkForm(request.POST, prefix=f"link{arrangement.pk}")
    if not form.is_valid():
        return song_detail(request, arrangement.song_id, bound=(arrangement.pk, form))
    link = form.save(commit=False)
    link.arrangement = arrangement
    link.save()
    messages.success(request, f"Added the {link.label} link.")
    return redirect("songs:detail", pk=arrangement.song_id)


@songs_required
@require_POST
def link_delete(request, pk):
    link = get_object_or_404(MediaLink, pk=pk)
    song_pk = link.arrangement.song_id
    link.delete()
    messages.success(request, f"Removed the {link.label} link.")
    return redirect("songs:detail", pk=song_pk)
