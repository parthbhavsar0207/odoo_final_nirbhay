"""
Club Views - Membership, Court, and Booking operations
Owned by Nayan (Backend: Membership and Bookings)
Styled by Pratik (Frontend templates & styling)
"""

from decimal import Decimal
from datetime import datetime, time
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, Http404

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
    Handoff to Pratik:
    - Route name: 'club:member_list'
    - Template path: 'club/members.html'
    - Context keys: 'page_title', 'members', 'plans'
    """
    search_query = request.GET.get('q', '').strip()
    tier_filter = request.GET.get('tier', '').strip()
    status_filter = request.GET.get('status', '').strip()

    members = Member.objects.select_related('plan').all()

    if search_query:
        members = members.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    if tier_filter:
        members = [m for m in members if m.current_plan and m.current_plan.tier == tier_filter]

    all_members = list(Member.objects.select_related('plan').all())
    eligible_member_ids = set()
    for member in all_members:
        plan = member.current_plan
        if member.is_club_member and member.is_active_member and plan is not None and plan.active:
            eligible_member_ids.add(member.pk)
    active_count = len(eligible_member_ids)
    suspended_count = sum(1 for m in all_members if m.is_suspended)
    expired_count = sum(1 for m in all_members if m.status_label == 'Expired')

    if status_filter == 'active':
        members = [m for m in members if m.pk in eligible_member_ids]
    elif status_filter == 'suspended':
        members = [m for m in members if m.is_suspended]
    elif status_filter == 'expired':
        members = [m for m in members if m.status_label == 'Expired']

    plans = MembershipPlan.objects.filter(active=True)
    form = MemberForm()

    context = {
        'page_title': 'Club Members',
        'members': members,
        'plans': plans,
        'form': form,
        'search_query': search_query,
        'tier_filter': tier_filter,
        'tier_choices': MembershipPlan.TIER_CHOICES,
        'status_filter': status_filter,
        'active_count': active_count,
        'suspended_count': suspended_count,
        'expired_count': expired_count,
        'total_members_count': len(all_members),
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
    Handoff to Pratik:
    - Route name: 'club:booking_list'
    - Template path: 'club/bookings.html'
    - Context keys: 'page_title', 'bookings', 'courts', 'selected_court'
    """
    court_id = request.GET.get('court')
    status_filter = request.GET.get('status')
    search_query = request.GET.get('q', '').strip()
    date_filter = request.GET.get('date', '').strip()

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

    courts = Court.objects.filter(active=True)
    booking_form = BookingForm()

    # Facility KPI Summary
    today_bookings_count = Booking.objects.filter(start_datetime__gte=today_start, start_datetime__lte=today_end).count()
    confirmed_count = Booking.objects.filter(status='confirmed').count()
    active_courts_count = courts.count()
    confirmed_revenue = Booking.objects.filter(status='confirmed').aggregate(total=Sum('price'))['total'] or Decimal('0.00')

    context = {
        'page_title': 'Court Bookings',
        'bookings': bookings,
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
    }
    return render(request, 'club/bookings.html', context)


def booking_create(request):
    """
    Creates and validates a new court booking for a member or walk-in.
    Enforces:
    - 60-minute duration on 30-minute start increments
    - GiST exclusion / no-overlap constraint on the same court
    - Max 2 confirmed bookings per member per club date (across standard & social play)
    - Backend controlled status (auto-confirms valid reservation)
    - Price calculated and snapshotted by backend from member plan or court standard rate
    Handoff to Pratik:
    - Route name: 'club:booking_create'
    - Form fields: 'court', 'booked_by_member', 'walkin_name', 'walkin_contact',
                   'start_datetime', 'booking_type'
    """
    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.status = 'confirmed'
            booking.price = booking.calculate_price()
            try:
                # Snapshots the price if confirmed and clean validations
                booking.full_clean()
                booking.save()
                messages.success(
                    request,
                    f"Booking #{booking.id} confirmed for {booking.court.name} at "
                    f"{timezone.localtime(booking.start_datetime).strftime('%Y-%m-%d %H:%M')}. "
                    f"Price snapshotted at ₹{booking.price}."
                )
                return redirect('club:booking_list')
            except ValidationError as err:
                if hasattr(err, 'message_dict'):
                    for field, errors in err.message_dict.items():
                        for error in errors:
                            form.add_error(field if field in form.fields else None, error)
                else:
                    form.add_error(None, err)
                messages.error(request, "Booking validation failed. See errors below.")
            except Exception as exc:
                messages.error(request, f"Database constraint violation: {exc}")
        else:
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

    context = {
        'page_title': 'Reserve Court',
        'form': form,
    }
    return render(request, 'club/booking_form.html', context)


def booking_cancel(request, pk):
    """
    Cancels a confirmed booking, immediately releasing the slot for other members.
    Handoff to Pratik:
    - Route name: 'club:booking_cancel'
    """
    booking = get_object_or_404(Booking, pk=pk)
    if request.method == 'POST':
        booking.status = 'cancelled'
        booking.save()
        messages.success(
            request,
            f"Booking #{booking.id} for {booking.court.name} was cancelled and the slot is now free."
        )
    return redirect('club:booking_list')


def booking_detail(request, pk):
    """
    Displays booking details and manages participants for social play.
    Handoff to Pratik:
    - Route name: 'club:booking_detail'
    - Context keys: 'booking', 'participants', 'participant_form'
    """
    booking = get_object_or_404(
        Booking.objects.select_related('court', 'booked_by_member', 'booked_by_member__plan'),
        pk=pk
    )
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
    }
    return render(request, 'club/booking_detail.html', context)


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
    context = {
        'page_title': 'Champions Club Live Court Availability',
        'courts': courts,
        'operating_hours': operating_hours,
        'court_grid': court_grid,
        'selected_date': selected_date,
        'today': today,
        'plans': MembershipPlan.objects.filter(active=True).order_by('id'),
        'total_confirmed_today': total_confirmed,
        'all_sports': get_all_sports_with_facilities(),
        'selected_sport': selected_sport,
        'selected_court': selected_court,
        'selected_time': selected_time,
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
            'action_url': '/club/bookings/new/',
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


