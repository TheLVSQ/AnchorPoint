"""Tiny fixed-window rate limiter built on Django's cache.

Best-effort abuse-blunting, not a hard security boundary: with the default
LocMemCache the counter is per-process (per gunicorn worker), so the effective
limit is roughly `limit * workers`. Good enough to stop junk floods and slow
brute force; swap in a shared cache (Redis) for exactness if ever needed.
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
