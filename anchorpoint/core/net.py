"""Request helpers that depend on how production is deployed.

Production sits behind a Cloudflare Tunnel: cloudflared connects to gunicorn on
127.0.0.1, so REMOTE_ADDR is always the tunnel, and X-Forwarded-For starts with
whatever the client chose to send. Cloudflare sets CF-Connecting-IP itself (a
client can't override it), so that is the only trustworthy client address.
"""
import ipaddress


def client_ip(request):
    """Best-effort real client IP for rate limiting and audit fields.

    Uses CF-Connecting-IP when it holds a valid IP, else REMOTE_ADDR. Never
    trusts X-Forwarded-For. Returns None if neither is a valid IP.
    """
    for candidate in (
        request.META.get("HTTP_CF_CONNECTING_IP", ""),
        request.META.get("REMOTE_ADDR", ""),
    ):
        candidate = candidate.strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None
