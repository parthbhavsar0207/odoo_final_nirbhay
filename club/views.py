"""
Club Views - Membership, Court, and Booking operations
Owned by Nayan (Backend: Membership and Bookings)
Styled by Pratik (Frontend templates & styling)
"""

import csv
import json
from django.conf import settings
from decimal import Decimal
from datetime import datetime, time, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse, Http404
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import Member, MembershipPlan, Court, Booking, BookingParticipant
from .forms import (
    MemberForm, BookingForm, BookingParticipantForm,
    MembershipPlanForm, MemberChangePlanForm
)
from .sports_catalog import (
    SPORTS_CATALOG, get_sport_data, get_all_sports_with_facilities
)
from commerce.models import Product
from .availability import availability_date, availability_grid



def member_list(request):
    """
    Lists registered club members with their assigned plan and active status.
    Supports live search (name, email, phone), filtering by tier and status,
    and server-side pagination with selectable page size (5, 10, 25, 50).
    """
    search_query = request.GET.get('q', '').strip()
    tier_filter = request.GET.get('tier', '').strip()
    status_filter = request.GET.get('status', '').strip()

    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', '10').strip()

    try:
        page_size_int = int(page_size)
        if page_size_int not in (5, 10, 25, 50):
            page_size_int = 10
    except (ValueError, TypeError):
        page_size_int = 10

    members = Member.objects.select_related('plan').all()

    # Search by member name, email, or phone
    if search_query:
        members = members.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    # Membership statistics
    all_members = list(Member.objects.select_related('plan').all())
    eligible_member_ids = set()
    for member in all_members:
        plan = member.current_plan
        if member.is_club_member and member.is_active_member and plan is not None and plan.active:
            eligible_member_ids.add(member.pk)
    active_count = len(eligible_member_ids)

    if tier_filter:
        if tier_filter in ('none', 'no_member'):
            tier_member_ids = {
                member.pk for member in all_members
                if not member.current_plan or not member.is_club_member
            }
        else:
            tier_member_ids = {
                member.pk for member in all_members
                if member.current_plan and member.current_plan.tier == tier_filter
            }
        members = members.filter(pk__in=tier_member_ids)

    suspended_count = sum(1 for m in all_members if m.is_suspended)
    expired_count = sum(
        1 for m in all_members if m.status_label == 'Expired'
    )

    # Status filtering
    if status_filter == 'active':
        members = members.filter(pk__in=eligible_member_ids)
    elif status_filter == 'suspended':
        members = members.filter(is_suspended=True)

    elif status_filter == 'expired':
        today = timezone.localdate()
        members = members.filter(
            membership_end__lt=today,
            is_suspended=False
        )

    # Sorting and pagination
    members = members.order_by('name', 'id')

    paginator = Paginator(members, page_size_int)
    page_obj = paginator.get_page(page_number)

    plans = MembershipPlan.objects.filter(active=True)
    form = MemberForm()

    context = {
        'page_title': 'Club Members',
        'members': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'plans': plans,
        'form': form,
        'search_query': search_query,
        'tier_filter': tier_filter,
        'tier_choices': [
            ('none', 'No Member'),
            ('junior', 'Junior'),
            ('silver', 'Silver'),
            ('gold', 'Gold'),
        ],
        'status_filter': status_filter,
        'selected_tier': tier_filter,
        'selected_status': status_filter,
        'active_count': active_count,
        'suspended_count': suspended_count,
        'expired_count': expired_count,
        'total_members_count': len(all_members),
        'page_size': page_size_int,
    }

    return render(request, 'club/members.html', context)



def member_create(request):
    """
    Registers a new member and assigns a membership plan.
    Handoff to Pratik:
    - Route name: 'club:member_create'
    - Form field names: 'name', 'email', 'phone', 'contact_details', 'plan',
                        'membership_start', 'membership_end', 'is_club_member', 'is_suspended'
    """
    if request.method == 'POST':
        form = MemberForm(request.POST)
        if form.is_valid():
            member = form.save()
            messages.success(request, f"Member '{member.name}' was successfully registered.")
            return redirect('club:member_list')
        else:
            messages.error(request, "Please correct the errors in the form below.")
    else:
        form = MemberForm()

    context = {
        'page_title': 'Register New Member',
        'form': form,
    }
    return render(request, 'club/member_form.html', context)


def member_edit(request, pk):
    """
    Edits an existing member record.
    Handoff to Pratik:
    - Route name: 'club:member_edit'
    """
    member = get_object_or_404(Member, pk=pk)
    if request.method == 'POST':
        form = MemberForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            messages.success(request, f"Member '{member.name}' was successfully updated.")
            return redirect('club:member_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = MemberForm(instance=member)

    context = {
        'page_title': f"Edit Member: {member.name}",
        'form': form,
        'member': member,
    }
    return render(request, 'club/member_form.html', context)


def booking_list(request):
    """
    Lists court reservations with status, price snapshots, and player names.
    Supports filtering by court and status, and server-side pagination with selectable page size.
    Handoff to Pratik:
    - Route name: 'club:booking_list'
    - Template path: 'club/bookings.html'
    - Context keys: 'page_title', 'bookings', 'courts', 'selected_court'
    """
    court_id = request.GET.get('court')
    status_filter = request.GET.get('status')
    search_query = request.GET.get('q', '').strip()
    date_filter = request.GET.get('date', '').strip()

    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', '10').strip()

    try:
        page_size_int = int(page_size)
        if page_size_int not in (5, 10, 25, 50):
            page_size_int = 10
    except (ValueError, TypeError):
        page_size_int = 10

    bookings = Booking.objects.select_related('court', 'booked_by_member', 'booked_by_member__plan')

    if court_id:
        bookings = bookings.filter(court_id=court_id)
    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if search_query:
        bookings = bookings.filter(
            Q(booked_by_member__name__icontains=search_query) |
            Q(walkin_name__icontains=search_query) |
            Q(court__name__icontains=search_query) |
            Q(id__iexact=search_query.lstrip('#'))
        )

    tz = timezone.get_current_timezone()
    today = timezone.localtime(timezone.now(), tz).date()
    today_start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()), tz)
    today_end = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.max.time()), tz)

    if date_filter == 'today':
        bookings = bookings.filter(start_datetime__gte=today_start, start_datetime__lte=today_end)

    bookings = bookings.order_by('-start_datetime', '-id')
    paginator = Paginator(bookings, page_size_int)
    page_obj = paginator.get_page(page_number)

    courts = Court.objects.filter(active=True)
    booking_form = BookingForm()

    # Facility KPI Summary
    today_bookings_count = Booking.objects.filter(start_datetime__gte=today_start, start_datetime__lte=today_end).count()
    confirmed_count = Booking.objects.filter(status='confirmed').count()
    active_courts_count = courts.count()
    confirmed_revenue = Booking.objects.filter(status='confirmed').aggregate(total=Sum('price'))['total'] or Decimal('0.00')

    context = {
        'page_title': 'Court Bookings',
        'bookings': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'courts': courts,
        'selected_court': court_id,
        'selected_status': status_filter,
        'search_query': search_query,
        'date_filter': date_filter,
        'today_bookings_count': today_bookings_count,
        'confirmed_count': confirmed_count,
        'active_courts_count': active_courts_count,
        'confirmed_revenue': confirmed_revenue,
        'form': booking_form,
        'page_size': page_size_int,
    }
    return render(request, 'club/bookings.html', context)


def _get_courts_and_members_data(today=None):
    """
    Serializes active courts and members with plan details for live reactive calculators.
    """
    if today is None:
        today = timezone.localdate()
    courts_data = {
        str(c.id): {
            'id': c.id,
            'name': c.name,
            'sport': c.get_sport_display(),
            'hourly_rate': float(c.hourly_rate),
        }
        for c in Court.objects.filter(active=True).order_by('id')
    }
    members_data = {
        str(m.id): {
            'id': m.id,
            'name': m.name,
            'tier': m.plan.tier if m.plan else 'none',
            'plan_name': m.plan.name if m.plan else 'No Plan',
            'plan_court_rate': float(m.plan.court_hourly_rate) if m.plan else None,
            'is_active': m.is_active_on_date(today),
        }
        for m in Member.objects.select_related('plan').all().order_by('name')
    }
    return courts_data, members_data


def api_calculate_price(request):
    """
    AJAX endpoint: Real-time price, member benefits, time difference, and conflict calculation.
    Enables instant in-page updates with zero page refresh when any dependent variable changes.
    """
    court_id = request.GET.get('court')
    member_id = request.GET.get('member')
    start_param = request.GET.get('start')
    today = timezone.localdate()

    if not court_id:
        return JsonResponse({'error': 'Missing court_id'}, status=400)

    try:
        court_id_int = int(court_id)
        court = Court.objects.get(id=court_id_int, active=True)
    except (ValueError, TypeError, Court.DoesNotExist):
        return JsonResponse({'error': 'Court not found or invalid court_id'}, status=404)

    member = None
    if member_id:
        try:
            member_id_int = int(member_id)
            member = Member.objects.select_related('plan').get(id=member_id_int)
        except (ValueError, TypeError, Member.DoesNotExist):
            member = None

    standard_rate = float(court.hourly_rate)
    final_price = standard_rate
    savings = 0.0
    rate_basis = f"Standard Rate (₹{standard_rate:.2f}/hr)"
    benefit_text = "Standard Rate Applied"

    if member and member.is_active_on_date(today) and member.plan:
        final_price = float(member.plan.court_hourly_rate)
        savings = max(0.0, standard_rate - final_price)
        rate_basis = f"{member.plan.name} Court Entitlement"
        if final_price == 0:
            benefit_text = f"100% Free · {member.plan.name}"
        else:
            benefit_text = f"₹{final_price:.2f}/hr · {member.plan.name}"
    elif member and not member.is_active_on_date(today):
        rate_basis = "Standard Rate (Member Inactive/Expired)"
        benefit_text = "Inactive: No Plan Benefit"

    # Time Difference & Duration
    time_diff = "--:-- → --:-- (60 min)"
    start_display = ""
    end_display = ""
    is_conflict = False
    conflict_message = ""

    if start_param:
        try:
            # Handle YYYY-MM-DDTHH:MM format
            tz = timezone.get_current_timezone()
            if 'T' in start_param:
                from datetime import datetime
                naive_dt = datetime.fromisoformat(start_param)
                start_dt = timezone.make_aware(naive_dt, tz)
            else:
                from datetime import datetime
                naive_dt = datetime.strptime(start_param, '%Y-%m-%d %H:%M')
                start_dt = timezone.make_aware(naive_dt, tz)

            end_dt = start_dt + timedelta(minutes=60)
            start_local = timezone.localtime(start_dt, tz)
            end_local = timezone.localtime(end_dt, tz)
            start_display = start_local.strftime('%I:%M %p')
            end_display = end_local.strftime('%I:%M %p')
            time_diff = f"{start_display} → {end_display} (60 min)"

            # Real-time overlap conflict check
            conflict_qs = Booking.objects.filter(
                court=court,
                status='confirmed',
                start_datetime__lt=end_dt,
                end_datetime__gt=start_dt,
            )
            if conflict_qs.exists():
                is_conflict = True
                conflict_message = f"Warning: {court.name} already has a confirmed booking at {start_local.strftime('%H:%M')}!"
        except Exception:
            pass

    return JsonResponse({
        'court_id': court.id,
        'court_name': court.name,
        'sport': court.get_sport_display(),
        'standard_rate': standard_rate,
        'final_price': final_price,
        'savings': savings,
        'rate_basis': rate_basis,
        'benefit_text': benefit_text,
        'time_diff': time_diff,
        'start_display': start_display,
        'end_display': end_display,
        'is_conflict': is_conflict,
        'conflict_message': conflict_message,
    })


def booking_create(request):
    """
    Creates and validates a new court booking for a member or walk-in.
    Supports both traditional POST redirection and real-time AJAX modal submissions.
    Enforces:
    - 60-minute duration on 30-minute start increments
    - GiST exclusion / no-overlap constraint on the same court
    - Max 2 confirmed bookings per member per club date (across standard & social play)
    - Backend controlled status (auto-confirms valid reservation)
    - Price calculated and snapshotted by backend from member plan or court standard rate
    """
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.POST.get('ajax') == '1' or
        'application/json' in request.headers.get('accept', '')
    )

    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.status = 'confirmed'
            booking.price = booking.calculate_price()

            # Process payment method and status
            pay_method = request.POST.get('payment_method')
            if pay_method and pay_method in Booking.PaymentMethod.values:
                booking.payment_method = pay_method
            elif not booking.payment_method:
                booking.payment_method = Booking.PaymentMethod.UPI

            # Enforce that member_tab can only be chosen when a valid member is attached
            if booking.payment_method == Booking.PaymentMethod.MEMBER_TAB and not booking.booked_by_member:
                booking.payment_method = Booking.PaymentMethod.UPI

            use_demo_gateway = (
                (settings.DEMO_PAYMENT_GATEWAY_ENABLED or settings.RAZORPAY_TEST_MODE_ENABLED)
                and request.POST.get('demo_gateway') == '1'
                and booking.price > Decimal('0.00')
                and booking.payment_method in (Booking.PaymentMethod.UPI, Booking.PaymentMethod.CARD)
            )
            if booking.price == Decimal('0.00') and booking.booked_by_member:
                booking.payment_status = Booking.PaymentStatus.WAIVED
                booking.payment_method = Booking.PaymentMethod.MEMBER_TAB
            elif use_demo_gateway:
                # The booking reserves its slot, but browser-submitted payment
                # status cannot claim success before the simulator completes.
                booking.payment_status = Booking.PaymentStatus.PENDING
            else:
                pay_status = request.POST.get('payment_status')
                # Never permit arbitrary waiver if price > 0
                if pay_status and pay_status in (Booking.PaymentStatus.PAID, Booking.PaymentStatus.PENDING):
                    booking.payment_status = pay_status
                else:
                    booking.payment_status = Booking.PaymentStatus.PAID

            try:
                with transaction.atomic():
                    # Concurrency safety: acquire row lock on member if booking for a member
                    if booking.booked_by_member_id:
                        Member.objects.select_for_update().get(id=booking.booked_by_member_id)

                    # Snapshots the price if confirmed and clean validations
                    booking.full_clean()
                    booking.save()
                local_start = timezone.localtime(booking.start_datetime)
                local_end = timezone.localtime(booking.end_datetime)
                payment_url = (
                    reverse(
                        'commerce:razorpay_payment' if settings.RAZORPAY_TEST_MODE_ENABLED
                        else 'commerce:demo_payment', args=['booking', booking.pk],
                    )
                    if use_demo_gateway else None
                )
                pay_detail = (
                    f"Demo payment pending: ₹{booking.price:.2f} via {booking.get_payment_method_display()}. No real charge."
                    if use_demo_gateway
                    else f"Settled ₹{booking.price:.2f} via {booking.get_payment_method_display()}"
                )
                success_msg = (
                    f"Booking #{booking.id} confirmed for {booking.court.name} at "
                    f"{local_start.strftime('%Y-%m-%d %H:%M')}. "
                    f"{pay_detail}."
                )

                if is_ajax:
                    player_name = (
                        booking.booked_by_member.name
                        if booking.booked_by_member
                        else (booking.walkin_name or "Walk-in Guest")
                    )
                    return JsonResponse({
                        'success': True,
                        'booking_id': booking.id,
                        'court_id': booking.court.id,
                        'court_name': booking.court.name,
                        'price': float(booking.price),
                        'payment_method': booking.payment_method,
                        'payment_method_display': booking.get_payment_method_display(),
                        'payment_status': booking.payment_status,
                        'payment_status_display': booking.get_payment_status_display(),
                        'payment_url': payment_url,
                        'slot_hour': local_start.strftime('%H:%M'),
                        'start_time': local_start.strftime('%H:%M'),
                        'end_time': local_end.strftime('%H:%M'),
                        'time_diff': f"{local_start.strftime('%H:%M')} → {local_end.strftime('%H:%M')}",
                        'player_display': player_name,
                        'booking_type': booking.get_booking_type_display(),
                        'message': success_msg,
                    })

                messages.success(request, success_msg)
                if payment_url:
                    return redirect(payment_url)
                return redirect('club:booking_list')
            except ValidationError as err:
                error_list = []
                if hasattr(err, 'message_dict'):
                    for field, errors in err.message_dict.items():
                        for error in errors:
                            form.add_error(field if field in form.fields else None, error)
                            error_list.append(str(error))
                else:
                    for error in err.messages:
                        form.add_error(None, error)
                        error_list.append(str(error))
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'message': " ".join(error_list) if error_list else "Validation failed.",
                        'errors': error_list,
                    }, status=400)
                messages.error(request, "Booking validation failed. See errors below.")
            except Exception as exc:
                logger.exception("Booking creation unexpected collision or database error: %s", exc)
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'message': "This court slot has already been reserved or conflicts with an existing booking. Please pick another available time.",
                        'errors': ["Court slot is unavailable due to an existing booking."],
                    }, status=400)
                messages.error(request, "This court slot has already been reserved or conflicts with an existing booking.")
        else:
            error_list = []
            for field, errors in form.errors.items():
                for error in errors:
                    error_list.append(f"{field}: {error}" if field != '__all__' else str(error))
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'message': " ".join(error_list) if error_list else "Invalid form submission.",
                    'errors': error_list,
                }, status=400)
            messages.error(request, "Please correct the errors in the booking form.")
    else:
        initial = {}
        court_id = request.GET.get('court')
        start_param = request.GET.get('start')
        member_id = request.GET.get('member')
        if court_id:
            initial['court'] = court_id
        if member_id:
            initial['booked_by_member'] = member_id
        if start_param:
            initial['start_datetime'] = start_param
        else:
            tz = timezone.get_current_timezone()
            now_local = timezone.localtime(timezone.now(), tz)
            initial['start_datetime'] = now_local.replace(minute=0, second=0).strftime('%Y-%m-%dT%H:%M')
        form = BookingForm(initial=initial)

    today = timezone.localdate()
    courts_data, members_data = _get_courts_and_members_data(today)

    context = {
        'page_title': 'Reserve Court',
        'demo_gateway_enabled': settings.DEMO_PAYMENT_GATEWAY_ENABLED,
        'razorpay_test_enabled': settings.RAZORPAY_TEST_MODE_ENABLED,
        'form': form,
        'courts_json': json.dumps(courts_data),
        'members_json': json.dumps(members_data),
    }
    return render(request, 'club/booking_form.html', context)


@require_POST
def booking_cancel(request, pk):
    """
    Cancels a confirmed booking, immediately releasing the slot for other members.
    Supports both traditional POST redirect and in-web real-time AJAX cancellations.
    Handoff to Pratik:
    - Route name: 'club:booking_cancel'
    """
    # Serialize cancellation with demo checkout, preserving any payment result
    # committed before this cancellation acquires the booking lock.
    with transaction.atomic():
        booking = get_object_or_404(Booking.objects.select_for_update(), pk=pk)
        booking.status = 'cancelled'
        booking.save()

    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.POST.get('ajax') == '1' or
        'application/json' in request.headers.get('accept', '')
    )

    local_start = timezone.localtime(booking.start_datetime)
    msg = f"Booking #{booking.id} for {booking.court.name} at {local_start.strftime('%H:%M')} was cancelled and the slot is now free."

    if is_ajax:
        return JsonResponse({
            'success': True,
            'booking_id': booking.id,
            'court_id': booking.court.id,
            'court_name': booking.court.name,
            'standard_price': float(booking.court.hourly_rate),
            'slot_hour': local_start.strftime('%H:%M'),
            'message': msg,
        })

    messages.success(request, msg)
    return redirect('club:booking_list')


def booking_export_csv(request):
    """
    Exports court reservations to a clean CSV file for accounting and operations.
    """
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="champions_club_bookings.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Booking ID', 'Court', 'Sport', 'Player / Member', 'Member Tier',
        'Start Time', 'End Time', 'Price (INR)', 'Payment Method', 'Payment Status', 'Status', 'Booking Type'
    ])

    bookings = Booking.objects.select_related(
        'court', 'booked_by_member', 'booked_by_member__plan'
    ).order_by('-start_datetime')

    for b in bookings:
        player = b.booked_by_member.name if b.booked_by_member else (b.walkin_name or "Walk-in Guest")
        tier = b.booked_by_member.plan.name if b.booked_by_member and b.booked_by_member.plan else "N/A"
        writer.writerow([
            b.id,
            b.court.name,
            b.court.get_sport_display(),
            player,
            tier,
            timezone.localtime(b.start_datetime).strftime('%Y-%m-%d %H:%M'),
            timezone.localtime(b.end_datetime).strftime('%Y-%m-%d %H:%M'),
            b.price,
            b.get_payment_method_display(),
            b.get_payment_status_display(),
            b.get_status_display(),
            b.get_booking_type_display(),
        ])
    return response


def booking_detail(request, pk):
    """
    Displays booking details and manages participants for social play.
    Supports both standard HTML view and AJAX JSON queries for modal inspection.
    Handoff to Pratik:
    - Route name: 'club:booking_detail'
    - Context keys: 'booking', 'participants', 'participant_form'
    """
    booking = get_object_or_404(
        Booking.objects.select_related('court', 'booked_by_member', 'booked_by_member__plan'),
        pk=pk
    )

    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.GET.get('ajax') == '1' or
        'application/json' in request.headers.get('accept', '')
    )

    tz = timezone.get_current_timezone()
    local_start = timezone.localtime(booking.start_datetime, tz)
    local_end = timezone.localtime(booking.end_datetime, tz)
    player_name = booking.booked_by_member.name if booking.booked_by_member else (booking.walkin_name or "Walk-in Guest")
    player_contact = booking.booked_by_member.phone if booking.booked_by_member else (booking.walkin_contact or "N/A")
    tier_name = booking.booked_by_member.plan.name if booking.booked_by_member and booking.booked_by_member.plan else "Walk-in (Standard)"
    tier_code = booking.booked_by_member.plan.tier if booking.booked_by_member and booking.booked_by_member.plan else "none"

    if is_ajax:
        return JsonResponse({
            'success': True,
            'id': booking.id,
            'court_id': booking.court.id,
            'court_name': booking.court.name,
            'sport': booking.court.get_sport_display(),
            'hourly_rate': float(booking.court.hourly_rate),
            'start_datetime': local_start.strftime('%Y-%m-%d %H:%M'),
            'end_datetime': local_end.strftime('%Y-%m-%d %H:%M'),
            'date_display': local_start.strftime('%A, %d %B %Y'),
            'time_diff': f"{local_start.strftime('%I:%M %p')} → {local_end.strftime('%I:%M %p')} (60 min)",
            'player_name': player_name,
            'player_contact': player_contact,
            'tier_name': tier_name,
            'tier_code': tier_code,
            'price': float(booking.price),
            'payment_method': booking.payment_method,
            'payment_method_display': booking.get_payment_method_display(),
            'payment_status': booking.payment_status,
            'payment_status_display': booking.get_payment_status_display(),
            'status': booking.status,
            'status_display': booking.get_status_display(),
            'booking_type': booking.get_booking_type_display(),
            'receipt_url': reverse('club:booking_receipt', kwargs={'pk': booking.id}),
            'cancel_url': reverse('club:booking_cancel', kwargs={'pk': booking.id}),
        })

    participants = booking.participants.select_related('member').all()
    participant_form = BookingParticipantForm()

    if request.method == 'POST':
        participant_form = BookingParticipantForm(request.POST)
        if participant_form.is_valid():
            participant = participant_form.save(commit=False)
            participant.booking = booking
            try:
                participant.full_clean()
                participant.save()
                messages.success(request, f"Participant added to booking #{booking.id}.")
                return redirect('club:booking_detail', pk=booking.id)
            except ValidationError as err:
                if hasattr(err, 'message_dict'):
                    for field, errors in err.message_dict.items():
                        for error in errors:
                            participant_form.add_error(field if field in participant_form.fields else None, error)
                else:
                    participant_form.add_error(None, err)
                messages.error(request, "Participant validation failed.")

    context = {
        'page_title': f"Booking #{booking.id} Details",
        'booking': booking,
        'participants': participants,
        'participant_form': participant_form,
        'demo_gateway_enabled': settings.DEMO_PAYMENT_GATEWAY_ENABLED,
        'razorpay_test_enabled': settings.RAZORPAY_TEST_MODE_ENABLED,
    }
    return render(request, 'club/booking_detail.html', context)


@xframe_options_sameorigin
def booking_receipt(request, pk):
    """
    Renders an official print-ready booking confirmation receipt / voucher for court reservations.
    """
    booking = get_object_or_404(
        Booking.objects.select_related('court', 'booked_by_member', 'booked_by_member__plan'),
        pk=pk
    )
    tz = timezone.get_current_timezone()
    local_start = timezone.localtime(booking.start_datetime, tz)
    local_end = timezone.localtime(booking.end_datetime, tz)
    player_name = booking.booked_by_member.name if booking.booked_by_member else (booking.walkin_name or "Walk-in Guest")
    player_contact = booking.booked_by_member.phone if booking.booked_by_member else (booking.walkin_contact or "N/A")
    tier_name = booking.booked_by_member.plan.name if booking.booked_by_member and booking.booked_by_member.plan else "Walk-in Guest"

    standard_price = booking.court.hourly_rate
    discount = max(Decimal('0.00'), standard_price - booking.price)

    context = {
        'page_title': f"Booking Voucher #{booking.id}",
        'booking': booking,
        'local_start': local_start,
        'local_end': local_end,
        'player_name': player_name,
        'player_contact': player_contact,
        'tier_name': tier_name,
        'standard_price': standard_price,
        'discount': discount,
        'demo_gateway_enabled': settings.DEMO_PAYMENT_GATEWAY_ENABLED,
        'razorpay_test_enabled': settings.RAZORPAY_TEST_MODE_ENABLED,
    }
    return render(request, 'club/booking_receipt.html', context)


@ensure_csrf_cookie
def public_availability(request):
    """Show honest public availability for 60-minute, half-hour-start sessions."""
    today = timezone.localdate()
    selected_date = availability_date(request.GET.get('date'), fallback=today)
    selected_sport = request.GET.get('sport', '').strip().lower()
    selected_court = request.GET.get('court', '').strip()
    selected_time = request.GET.get('time', '').strip()

    courts = Court.objects.filter(active=True).order_by('id')
    if selected_sport:
        courts = courts.filter(sport=selected_sport)
    if selected_court:
        if (
            not selected_court.isascii()
            or not selected_court.isdigit()
            or len(selected_court) > 19
            or not 1 <= int(selected_court) <= 9223372036854775807
        ):
            raise Http404("Court does not exist.")
        courts = courts.filter(id=int(selected_court))
    courts = list(courts)
    operating_hours, court_grid, total_confirmed = availability_grid(courts, selected_date)

    plans = MembershipPlan.objects.filter(active=True).order_by('id')
    tier_rates = {plan.tier: float(plan.court_hourly_rate) for plan in plans}
    tier_rates.setdefault('gold', 0.0)
    tier_rates.setdefault('silver', 200.0)
    tier_rates.setdefault('junior', 150.0)
    operating_slots = []
    for start in operating_hours:
        slot_start = datetime.combine(
            selected_date, datetime.strptime(start, '%H:%M').time()
        )
        slot_end = slot_start + timedelta(minutes=60)
        hour = slot_start.hour
        time_band = "Morning" if hour < 12 else ("Afternoon" if hour < 17 else "Evening Prime")
        operating_slots.append({
            'start': start,
            'end': slot_end.strftime('%H:%M'),
            'time_band': time_band,
            'label': f"{start} → {slot_end.strftime('%H:%M')}",
        })
    all_sports = get_all_sports_with_facilities()
    courts_data, _ = _get_courts_and_members_data(selected_date)
    context = {
        'page_title': 'Champions Club Live Court Availability',
        'courts': courts,
        'operating_hours': operating_hours,
        'operating_slots': operating_slots,
        'court_grid': court_grid,
        'selected_date': selected_date,
        'today': today,
        'plans': plans,
        'tier_rates': tier_rates,
        'total_confirmed_today': total_confirmed,
        'all_sports': all_sports,
        'selected_sport': selected_sport,
        'selected_court': selected_court,
        'selected_time': selected_time,
        'courts_json': json.dumps(courts_data),
    }
    return render(request, 'club/public_availability.html', context)


# ==========================================================================
# Activities Section (Data-Driven Shared Architecture)
# ==========================================================================

def sports_directory(request):
    """
    Public Activities Directory showing all sports and facilities.
    Data-driven listing with real facility availability counts.
    """
    search_q = request.GET.get('q', '').strip().lower()
    selected_category = request.GET.get('category', '').strip()

    all_sports = get_all_sports_with_facilities()

    if search_q:
        all_sports = [
            s for s in all_sports
            if search_q in s['name'].lower() or search_q in s['category'].lower() or search_q in s['description'].lower()
        ]
    if selected_category:
        all_sports = [s for s in all_sports if s['category'].lower() == selected_category.lower()]

    categories = sorted(list(set(s['category'] for s in SPORTS_CATALOG.values())))

    context = {
        'page_title': 'Activities & Facilities · Champions Club',
        'sports': all_sports,
        'categories': categories,
        'selected_category': selected_category,
        'search_q': search_q,
    }
    return render(request, 'club/sports_directory.html', context)


def sport_detail(request, sport_slug):
    """Show active facilities and full-session availability for one activity."""
    sport_info = get_sport_data(sport_slug)
    if not sport_info:
        raise Http404(f"Sport '{sport_slug}' is not recognized in the Champions Club catalog.")
    courts = list(Court.objects.filter(
        sport=sport_info['slug'], active=True,
    ).order_by('name'))
    today = timezone.localdate()
    selected_date = availability_date(request.GET.get('date'), fallback=today)
    operating_hours, court_slots, _ = availability_grid(courts, selected_date)
    context = {
        'page_title': f"{sport_info['name']} Facilities & Availability · Champions Club",
        'sport': sport_info,
        'has_facilities': bool(courts),
        'courts': courts,
        'court_slots': court_slots,
        'operating_hours': operating_hours,
        'selected_date': selected_date,
        'today': today,
    }
    return render(request, 'club/sport_detail.html', context)


# ==========================================================================
# Membership Plan Management & Member Upgrades/Downgrades
# ==========================================================================

def plan_list(request):
    """
    Staff-facing membership plans list.
    Displays all plans (active & inactive) with member counts and plan benefits.
    """
    plans = list(MembershipPlan.objects.order_by('-active', 'membership_fee'))
    counts = {plan.pk: 0 for plan in plans}
    for member in Member.objects.select_related('plan').all():
        plan = member.current_plan
        if plan is not None:
            counts[plan.pk] = counts.get(plan.pk, 0) + 1
    for plan in plans:
        plan.member_count = counts[plan.pk]

    context = {
        'page_title': 'Membership Plans Management · Champions Club',
        'plans': plans,
    }
    return render(request, 'club/plan_list.html', context)


def plan_create(request):
    """
    Staff-facing view to create a new MembershipPlan.
    """
    if request.method == 'POST':
        form = MembershipPlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Membership Plan '{plan.name}' was successfully created.")
            return redirect('club:plan_list')
        else:
            messages.error(request, "Please correct the errors in the plan form.")
    else:
        form = MembershipPlanForm()

    context = {
        'page_title': 'Create New Membership Plan',
        'form': form,
    }
    return render(request, 'club/plan_form.html', context)


def plan_edit(request, pk):
    """
    Staff-facing view to edit an existing MembershipPlan.
    """
    plan = get_object_or_404(MembershipPlan, pk=pk)
    if request.method == 'POST':
        form = MembershipPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, f"Membership Plan '{plan.name}' was updated successfully.")
            return redirect('club:plan_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = MembershipPlanForm(instance=plan)

    context = {
        'page_title': f"Edit Plan: {plan.name}",
        'form': form,
        'plan': plan,
    }
    return render(request, 'club/plan_form.html', context)


def plan_toggle_active(request, pk):
    """
    Staff-facing action to activate or deactivate a membership plan without deleting referenced records.
    """
    plan = get_object_or_404(MembershipPlan, pk=pk)
    if request.method == 'POST':
        plan.active = not plan.active
        plan.save()
        status_word = "activated" if plan.active else "deactivated"
        messages.success(request, f"Plan '{plan.name}' has been {status_word}.")
    return redirect('club:plan_list')


def public_plans(request):
    """
    Customer-facing membership plans screen.
    Clear, transparent display of active plans, pricing, and privileges.
    """
    plans = MembershipPlan.objects.filter(active=True).order_by('membership_fee')
    context = {
        'page_title': 'Membership Plans &amp; Tiers · Champions Club',
        'plans': plans,
    }
    return render(request, 'club/public_plans.html', context)


def member_change_plan(request, pk):
    """
    Staff-facing view to change a member's plan (Upgrade or Downgrade).
    Requires explicit effective date and confirmation.
    Preserves all past historical price snapshots on past bookings and sales.
    """
    from .plan_changes import change_membership_plan

    member = get_object_or_404(Member.objects.select_related('plan'), pk=pk)

    if request.method == 'POST':
        form = MemberChangePlanForm(request.POST)
        if form.is_valid():
            new_plan = form.cleaned_data['new_plan']
            effective_date = form.cleaned_data['effective_date']
            notes = form.cleaned_data.get('notes', '')

            try:
                change_membership_plan(
                    member_id=member.pk, plan_id=new_plan.pk,
                    effective_date=effective_date, notes=notes,
                )
            except ValidationError as error:
                for field, errors in error.message_dict.items():
                    for message in errors:
                        form.add_error(field if field in form.fields else None, message)
            else:
                verb = 'scheduled' if effective_date > timezone.localdate() else 'applied'
                messages.success(
                    request,
                    f"Plan change to '{new_plan.name}' {verb} for {member.name}, effective {effective_date}. "
                    f"Membership dates and historical booking/sale amounts remain unchanged."
                )
                return redirect('club:member_list')
        else:
            messages.error(request, "Please confirm the plan change and correct any errors below.")
    else:
        form = MemberChangePlanForm(initial={
            'effective_date': timezone.localdate(),
        })

    active_plans = MembershipPlan.objects.filter(active=True).order_by('membership_fee')

    context = {
        'page_title': f"Change Membership Plan: {member.name}",
        'member': member,
        'form': form,
        'active_plans': active_plans,
    }
    return render(request, 'club/member_change_plan.html', context)


# ==========================================================================
# Real-Time Search Suggestions API (Public & Secure)
# ==========================================================================

def search_suggestions_api(request):
    """
    Returns matching suggestions for site search across:
    - Sports
    - Active Facilities / Courts
    - Active Commerce Products (Shop & Bar)
    - Active Membership Plans
    Privacy guarantee: ZERO private member details (name, email, phone) are queried or returned.
    """
    q = request.GET.get('q', '').strip().lower()
    if not q or len(q) < 1:
        return JsonResponse({'suggestions': []})

    suggestions = []

    # 1. Sports in catalog
    for slug, sport in SPORTS_CATALOG.items():
        if q in sport['name'].lower() or q in sport['category'].lower() or q in slug:
            suggestions.append({
                'type': 'Sport',
                'title': sport['name'],
                'subtitle': f"{sport['category']} · {sport['surface_types'][:45]}...",
                'url': f"/club/sports/{slug}/",
                'icon': sport['icon'],
            })

    # 2. Active Courts / Facilities
    courts = Court.objects.filter(active=True).filter(
        Q(name__icontains=q) | Q(sport__icontains=q)
    )[:6]
    for c in courts:
        suggestions.append({
            'type': 'Facility',
            'title': c.name,
            'subtitle': f"{c.get_sport_display()} · Cap {c.capacity} · ₹{c.hourly_rate}/hr",
            'url': f"/club/sports/{c.sport}/",
            'icon': 'stadium',
        })

    # 3. Active Commerce Products
    products = Product.objects.filter(is_active=True).filter(
        Q(name__icontains=q) | Q(category__icontains=q)
    )[:6]
    for p in products:
        suggestions.append({
            'type': 'Shop & Bar',
            'title': p.name,
            'subtitle': f"{p.get_category_display()} · ₹{p.price} in stock ({p.stock_quantity})",
            'url': p.get_absolute_url(),
            'icon': 'shopping_bag',
        })

    # 4. Active Membership Plans
    plans = MembershipPlan.objects.filter(active=True).filter(
        Q(name__icontains=q) | Q(tier__icontains=q)
    )[:4]
    for pl in plans:
        suggestions.append({
            'type': 'Membership',
            'title': pl.name,
            'subtitle': f"₹{pl.membership_fee}/yr · {pl.get_tier_display()} Benefits",
            'url': "/club/plans/public/",
            'icon': 'badge',
        })

    return JsonResponse({'suggestions': suggestions[:12]})


# ==========================================================================
# Curated Help Chatbot Assistant API
# ==========================================================================

def help_bot_faq_api(request):
    """
    Curated FAQ knowledge base for customer-facing Help Chatbot widget.
    Provides instant answers, structured recommendations, and real contact fallback.
    """
    q = request.GET.get('q', '').strip().lower()

    active_plans = list(MembershipPlan.objects.filter(active=True).order_by('membership_fee', 'pk'))
    if active_plans:
        plan_answer = "Current active membership plans: " + "; ".join(
            f"{plan.name}: fee ₹{plan.membership_fee}, court ₹{plan.court_hourly_rate}/hour, "
            f"shop {plan.shop_discount_percent}% and bar {plan.bar_discount_percent}%"
            for plan in active_plans
        ) + ". Benefits require an eligible membership and active plan. Members may play in up to two confirmed bookings per local day."
    else:
        plan_answer = "No active membership plans are currently configured. Check with reception before purchasing a membership."
    configured = sorted(set(Court.objects.filter(active=True).values_list('sport', flat=True)))
    configured_names = [SPORTS_CATALOG[slug]['name'] for slug in configured if slug in SPORTS_CATALOG]
    sports_answer = (
        "Our Activities directory describes the club's sports. Currently configured active facilities: "
        + (", ".join(configured_names) if configured_names else "none")
        + ". Open an activity or the live schedule to check its actual availability."
    )
    shop_count = Product.objects.filter(is_active=True, category='shop').count()
    bar_count = Product.objects.filter(is_active=True, category='bar').count()
    commerce_answer = (
        f"The live Pro Shop has {shop_count} active products and the Bar has {bar_count}. "
        "Product cards show current prices and stock. Select Member sale to apply eligible plan benefits; "
        "prices, discounts and inventory are checked when completing the sale."
    )

    FAQS = [
        {
            'id': 'sports',
            'topic': 'Sports & Facilities',
            'keywords': ['sport', 'sports', 'court', 'courts', 'tennis', 'badminton', 'squash', 'cricket', 'football', 'basketball', 'volleyball', 'table tennis', 'pickleball', 'swimming', 'facility', 'pool'],
            'question': 'What sports and athletic facilities are available at Champions Club?',
            'answer': sports_answer,
            'action_label': 'Explore Activities',
            'action_url': '/club/sports/',
        },
        {
            'id': 'availability',
            'topic': 'Live Court Availability',
            'keywords': ['available', 'availability', 'schedule', 'free', 'slots', 'matrix', 'hours', 'time', 'timing'],
            'question': 'How can I check if courts or practice nets are free today?',
            'answer': 'Our Live Availability Matrix provides real-time court schedules from 06:00 to 22:00 daily. You can filter by sport, court, and date to spot free 60-minute session slots.',
            'action_label': 'View Live Availability',
            'action_url': '/club/availability/',
        },
        {
            'id': 'booking',
            'topic': 'Making a Reservation',
            'keywords': ['book', 'booking', 'reserve', 'reservation', 'walkin', 'guest', 'cost', 'fee', 'price'],
            'question': 'Can walk-in guests reserve courts, and how long are sessions?',
            'answer': 'Yes! Both verified members and walk-in guests can book sessions. All sessions last exactly 60 minutes and start every 30 minutes. Prices are snapshotted upon confirmation based on court standard rates or member plan perks.',
            'action_label': 'Reserve Court Slot',
            'action_url': '/club/availability/',
        },
        {
            'id': 'plans',
            'topic': 'Membership Tiers',
            'keywords': ['membership', 'plan', 'plans', 'tier', 'gold', 'silver', 'junior', 'subscription', 'perks', 'benefits', 'discount'] + [plan.tier for plan in active_plans],
            'question': 'What are the membership plans and what discounts do they offer?',
            'answer': plan_answer,
            'action_label': 'View Membership Plans',
            'action_url': '/club/plans/public/',
        },
        {
            'id': 'commerce',
            'topic': 'Pro Shop & Bar',
            'keywords': ['commerce', 'shop', 'bar', 'cafe', 'cafeteria', 'drink', 'water', 'racquet', 'racket', 'equipment', 'refreshment', 'pos', 'balls', 'food'],
            'question': 'What equipment and refreshments are sold on site?',
            'answer': commerce_answer,
            'action_label': 'Visit Club Pro Shop & Bar',
            'action_url': '/commerce/',
        },
        {
            'id': 'contact',
            'topic': 'Front Desk & Contact',
            'keywords': ['contact', 'phone', 'email', 'address', 'location', 'help', 'desk', 'reception', 'coach', 'coaching'],
            'question': 'How do I contact customer support or visit the facility?',
            'answer': 'Our front desk operations team is on site daily from 06:00 to 22:00 at North Lawn, Champions Club. You can reach us by email at operations@championsclub.com or phone at +91 98765 43210.',
            'action_label': 'Back to Club Home',
            'action_url': '/',
        },
    ]

    if not q:
        return JsonResponse({'faqs': FAQS})

    matched = []
    for faq in FAQS:
        if any(k in q for k in faq['keywords']) or q in faq['question'].lower() or q in faq['answer'].lower():
            matched.append(faq)

    return JsonResponse({
        'faqs': matched if matched else [],
        'fallback': {
            'message': 'No direct FAQ matched your inquiry. Our front desk concierge is ready to assist you directly at operations@championsclub.com or +91 98765 43210.',
            'action_label': 'View Sports Facilities',
            'action_url': '/club/sports/',
        } if not matched else None
    })


def api_members_list(request):
    """
    Returns active/registered club members for the reservation modal member selector.
    """
    today = timezone.localdate()
    target_date = availability_date(request.GET.get('date'), fallback=today)
    _, members_data = _get_courts_and_members_data(target_date)
    return JsonResponse({'members': members_data})



