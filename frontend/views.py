"""
Champions Club Frontend Views
Managed by Pratik (Frontend & UI integration).
Coordinates owner dashboard presentation and live aggregations.
"""

from decimal import Decimal
from datetime import datetime, time
from django.shortcuts import render
from django.db.models import Sum, F
from django.utils import timezone

from club.models import Member, Court, Booking, MembershipPlan
from commerce.models import Sale, Product


def dashboard_view(request):
    """
    Owner Overview Dashboard.
    Pulls live data from PostgreSQL for courts, members, and bookings.
    Notes commerce/dues dependencies awaiting Utkarsh's models.
    """
    total_courts = Court.objects.filter(active=True).count()
    active_members = Member.objects.filter(is_club_member=True, is_suspended=False).count()
    total_members = Member.objects.count()

    # Bookings stats
    confirmed_bookings = Booking.objects.filter(status='confirmed')
    total_confirmed_count = confirmed_bookings.count()
    total_bookings_count = Booking.objects.count()

    # Revenue aggregation from snapshotted prices
    revenue_agg = confirmed_bookings.aggregate(total=Sum('price'))
    court_revenue = revenue_agg['total'] if revenue_agg['total'] is not None else Decimal('0.00')

    # Recent live bookings
    recent_bookings = Booking.objects.select_related(
        'court', 'booked_by_member', 'booked_by_member__plan'
    ).order_by('-start_datetime')[:6]

    # Today's bookings
    tz = timezone.get_current_timezone()
    today = timezone.localtime(timezone.now(), tz).date()
    today_start = timezone.make_aware(datetime.combine(today, time.min), tz)
    today_end = timezone.make_aware(datetime.combine(today, time.max), tz)
    today_bookings_count = confirmed_bookings.filter(
        start_datetime__gte=today_start,
        start_datetime__lte=today_end
    ).count()

    # Calculate utilization for today (assuming 16 operating hours per court: 06:00 to 22:00)
    total_bookable_hours_today = total_courts * 16 if total_courts > 0 else 1
    utilization_rate = round((today_bookings_count / total_bookable_hours_today) * 100, 1)

    # Commerce stats from completed sales
    completed_sales = Sale.objects.filter(status='completed')
    commerce_rev_agg = completed_sales.aggregate(total=Sum('total'))
    commerce_revenue = commerce_rev_agg['total'] if commerce_rev_agg['total'] is not None else Decimal('0.00')
    completed_sales_count = completed_sales.count()

    # Low stock alerts (products where stock <= threshold)
    low_stock_products = Product.objects.filter(
        is_active=True,
        stock_quantity__lte=F('low_stock_threshold')
    ).order_by('stock_quantity')[:4]

    plans = MembershipPlan.objects.filter(active=True)

    context = {
        'page_title': 'Financial & Facility Performance',
        'total_courts': total_courts,
        'active_members': active_members,
        'total_members': total_members,
        'total_confirmed_count': total_confirmed_count,
        'total_bookings_count': total_bookings_count,
        'court_revenue': court_revenue,
        'commerce_revenue': commerce_revenue,
        'completed_sales_count': completed_sales_count,
        'low_stock_products': low_stock_products,
        'today_bookings_count': today_bookings_count,
        'total_bookable_hours_today': total_bookable_hours_today,
        'utilization_rate': utilization_rate,
        'recent_bookings': recent_bookings,
        'today_date': today,
        'plans': plans,
    }
    return render(request, 'dashboard/index.html', context)
