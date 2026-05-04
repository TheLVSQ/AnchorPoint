from django.utils import timezone

from checkin.models import CheckInSession


def get_or_create_session(config, window, user=None):
    """
    Get or create a CheckInSession for today from a config + window.

    If a session already exists for this config+window+date, return it.
    Otherwise create one with times copied from the window and rooms from the config.
    """
    today = timezone.localdate()

    session = CheckInSession.objects.filter(
        configuration=config,
        window=window,
        date=today,
    ).first()

    if session:
        return session

    session = CheckInSession.objects.create(
        configuration=config,
        window=window,
        name=config.name,
        date=today,
        checkin_opens=window.checkin_opens,
        checkin_closes=window.checkin_closes,
        event_starts=window.event_starts,
        event_ends=window.event_ends,
        created_by=user,
    )
    session.rooms.set(config.rooms.all())
    return session
