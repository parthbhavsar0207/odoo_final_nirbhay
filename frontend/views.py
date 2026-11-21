"""
Champions Club Frontend Views
Managed by Pratik (Frontend & UI integration).
Coordinates owner dashboard presentation and live aggregations.
"""

from decimal import Decimal
from datetime import datetime, time, timedelta
from django.shortcuts import render
from django.db.models import Sum
from django.utils import timezone

from club.models import Member, Court, Booking, MembershipPlan
from commerce.reporting import commerce_dashboard_summary


def dashboard_view(request):
    """
    Owner Overview Dashboard.
    Pulls live database booking values, completed sales and inventory alerts.
    """
    total_courts = Court.objects.filter(active=True).count()
    today = timezone.localdate()
    active_members = 0
    for member in Member.objects.select_related('plan').all():
        plan = member.effective_plan_on_date(today)
        if member.is_club_member and member.is_active_on_date(today) and plan is not None and plan.active:
            active_members += 1
    total_members = Member.objects.count()

    # Bookings stats
    confirmed_bookings = Booking.objects.filter(status='confirmed')
    total_confirmed_count = confirmed_bookings.count()
    total_bookings_count = Booking.objects.count()

    # A confirmed booking snapshot is booking value, not collected revenue.
    revenue_agg = confirmed_bookings.aggregate(total=Sum('price'))
    confirmed_booking_value = revenue_agg['total'] if revenue_agg['total'] is not None else Decimal('0.00')

    # Recent live bookings
    recent_bookings = Booking.objects.select_related(
        'court', 'booked_by_member', 'booked_by_member__plan'
    ).order_by('-start_datetime')[:5]

    # Today's bookings
    tz = timezone.get_current_timezone()
    today_start = timezone.make_aware(datetime.combine(today, time.min), tz)
    today_end = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min), tz)
    today_confirmed_bookings = confirmed_bookings.filter(
        start_datetime__gte=today_start,
        start_datetime__lt=today_end
    )
    today_bookings_count = today_confirmed_bookings.count()
    opening = timezone.make_aware(datetime.combine(today, time(6)), tz)
    closing = timezone.make_aware(datetime.combine(today, time(22)), tz)
    utilization_bookings = confirmed_bookings.filter(
        court__active=True, start_datetime__lt=closing, end_datetime__gt=opening,
    )
    today_booked_hours = sum(
        (min(end, closing) - max(start, opening)).total_seconds() / 3600
        for start, end in utilization_bookings.values_list('start_datetime', 'end_datetime')
    )

    # Use confirmed active-court time within the existing 06:00-22:00 window.
    total_bookable_hours_today = total_courts * 16
    utilization_rate = (
        round((today_booked_hours / total_bookable_hours_today) * 100, 1)
        if total_bookable_hours_today else 0
    )

    plans = MembershipPlan.objects.filter(active=True)

    context = {
        'page_title': 'Financial & Facility Performance',
        'total_courts': total_courts,
        'active_members': active_members,
        'total_members': total_members,
        'total_confirmed_count': total_confirmed_count,
        'total_bookings_count': total_bookings_count,
        'confirmed_booking_value': confirmed_booking_value,
        'today_bookings_count': today_bookings_count,
        'today_booked_hours': today_booked_hours,
        'total_bookable_hours_today': total_bookable_hours_today,
        'utilization_rate': utilization_rate,
        'recent_bookings': recent_bookings,
        'today_date': today,
        'plans': plans,
    }
    context.update(commerce_dashboard_summary(today=today))
    return render(request, 'dashboard/index.html', context)
