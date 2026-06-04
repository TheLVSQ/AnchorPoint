from django.utils import timezone

from checkin.models import CheckInSession


def get_or_create_session(config, window, user=None):
    """
    Get or create a CheckInSession for today from a config + window.

    If a session already exists for this config+window+date, return it.
    Otherwise create one with times copied from the window and rooms from the config.
    """
    today = timezone.localdate()

    # get_or_create + the (configuration, window, date) unique constraint make
    # this race-safe: two kiosks hitting lookup at once can't create duplicate
    # sessions that would split check-ins and break the dashboard counts.
    session, created = CheckInSession.objects.get_or_create(
        configuration=config,
        window=window,
        date=today,
        defaults={
            "name": config.name,
            "checkin_opens": window.checkin_opens,
            "checkin_closes": window.checkin_closes,
            "event_starts": window.event_starts,
            "event_ends": window.event_ends,
            "created_by": user,
        },
    )
    if created:
        session.rooms.set(config.rooms.all())
    return session
