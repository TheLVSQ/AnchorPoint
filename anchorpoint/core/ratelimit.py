"""Tiny fixed-window rate limiter built on Django's cache.

Fixed-window counters in the shared DatabaseCache (settings.CACHES), so a limit
holds across gunicorn workers. Key on core.net.client_ip(), never on
X-Forwarded-For (client-controlled behind Cloudflare).
"""

from django.core.cache import cache


def too_many(key, limit, window_seconds):
    """Record a hit for `key` and return True once it exceeds `limit` within
    `window_seconds` (fixed window, anchored on the first hit)."""
    cache.add(key, 0, window_seconds)  # start the window only if absent
    try:
        count = cache.incr(key)
    except ValueError:  # window expired between add and incr — treat as first hit
        cache.set(key, 1, window_seconds)
        count = 1
    return count > limit
