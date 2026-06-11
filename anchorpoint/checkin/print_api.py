"""Agent-facing print API.

Token-authenticated JSON endpoints (plain Django views, matching the existing
api_session_stats style — no DRF). A local print agent pairs once with a code,
then polls for jobs and acks them. All calls are outbound from the agent, so no
inbound networking to the LAN is required.
"""

import functools
import json

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import PrintAgent, PrintJob, hash_agent_token


def _agent_from_request(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):].strip()
    if not token:
        return None
    return PrintAgent.objects.filter(
        token_hash=hash_agent_token(token), is_active=True
    ).first()


def agent_required(view):
    """Authenticate by agent token and record a heartbeat (last_seen_at)."""
    @csrf_exempt
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        agent = _agent_from_request(request)
        if agent is None:
            return JsonResponse({"detail": "Invalid or missing agent token."}, status=401)
        PrintAgent.objects.filter(pk=agent.pk).update(last_seen_at=timezone.now())
        request.print_agent = agent
        return view(request, *args, **kwargs)
    return wrapper


@csrf_exempt
@require_POST
def pair(request):
    """Exchange a pairing code for a long-lived agent token (returned once)."""
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    code = (body.get("pairing_code") or "").strip().upper()
    if not code:
        return JsonResponse({"detail": "pairing_code is required."}, status=400)

    agent = PrintAgent.objects.filter(pairing_code=code).first()
    if (
        agent is None
        or not agent.pairing_expires_at
        or agent.pairing_expires_at < timezone.now()
    ):
        return JsonResponse({"detail": "Invalid or expired pairing code."}, status=400)

    token = agent.complete_pairing()
    return JsonResponse({"token": token, "agent_name": agent.name})


@agent_required
@require_GET
def next_job(request):
    """Atomically claim and return the next pending job for this agent."""
    agent = request.print_agent
    with transaction.atomic():
        job = (
            PrintJob.objects.select_for_update(skip_locked=True)
            .filter(agent=agent, status=PrintJob.PENDING)
            .order_by("created_at")
            .first()
        )
        if job is None:
            return HttpResponse(status=204)
        job.status = PrintJob.CLAIMED
        job.claimed_at = timezone.now()
        job.attempts += 1
        job.save(update_fields=["status", "claimed_at", "attempts"])

    return JsonResponse({
        "id": job.pk,
        "kind": job.kind,
        "description": job.description,
        "image_url": f"/checkin/api/print/{job.pk}/image",
        "media_width_mm": agent.label_width_mm,
    })


@agent_required
@require_GET
def job_image(request, job_id):
    """Return the PNG bytes for a claimed job (authed; not via public media)."""
    job = PrintJob.objects.filter(pk=job_id, agent=request.print_agent).first()
    if job is None:
        return JsonResponse({"detail": "Not found."}, status=404)
    return HttpResponse(bytes(job.image_data), content_type="image/png")


@agent_required
@require_POST
def ack_job(request, job_id):
    """Report the result of a print attempt."""
    job = PrintJob.objects.filter(pk=job_id, agent=request.print_agent).first()
    if job is None:
        return JsonResponse({"detail": "Not found."}, status=404)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        body = {}

    if body.get("status") == "printed":
        job.status = PrintJob.PRINTED
        job.printed_at = timezone.now()
        job.error_message = ""
    else:
        job.status = PrintJob.FAILED
        job.error_message = (body.get("error") or "")[:2000]
    job.save(update_fields=["status", "printed_at", "error_message"])
    return JsonResponse({"ok": True})
