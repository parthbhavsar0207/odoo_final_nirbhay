"""Build public availability for sixty-minute sessions starting every half-hour."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from .models import Booking


SESSION_LENGTH = timedelta(minutes=60)
START_INTERVAL = timedelta(minutes=30)
OPENING_TIME = time(6)
CLOSING_TIME = time(22)


def availability_date(value, *, fallback):
    """Preserve the public date fallback without exposing parsing exceptions."""
    if not value or len(value) != 10:
        return fallback
    try:
        selected = date.fromisoformat(value)
    except ValueError:
        return fallback
    # The query's exclusive next-day boundary must be representable.
    return fallback if selected == date.max else selected


def availability_grid(courts, selected_date):
    """Return template rows whose free cells represent a full available session.

    A cell is unavailable if any confirmed interval overlaps its sixty-minute
    interval. Endpoint equality is allowed, matching the PostgreSQL [) range.
    Public row payloads contain no booking/member identity.
    """
    courts = list(courts)
    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(selected_date, time.min), tz)
    day_end = timezone.make_aware(
        datetime.combine(selected_date + timedelta(days=1), time.min), tz,
    )
    opening = timezone.make_aware(datetime.combine(selected_date, OPENING_TIME), tz)
    closing = timezone.make_aware(datetime.combine(selected_date, CLOSING_TIME), tz)
    starts = []
    cursor = opening
    while cursor + SESSION_LENGTH <= closing:
        starts.append(cursor)
        cursor += START_INTERVAL
    operating_hours = [start.strftime("%H:%M") for start in starts]

    bookings = list(Booking.objects.filter(
        status="confirmed", court_id__in=[court.pk for court in courts],
        start_datetime__lt=day_end, end_datetime__gt=day_start,
    ).values_list("court_id", "start_datetime", "end_datetime"))
    by_court = defaultdict(list)
    for court_id, start, end in bookings:
        by_court[court_id].append((start, end))

    rows = []
    for court in courts:
        slots = []
        for label, start in zip(operating_hours, starts):
            end = start + SESSION_LENGTH
            blocked = any(
                booking_start < end and booking_end > start
                for booking_start, booking_end in by_court[court.pk]
            )
            slots.append((label, {"status": "booked" if blocked else "free"}))
        rows.append({"court": court, "slots": slots})
    return operating_hours, rows, len(bookings)
