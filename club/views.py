"""
Club Views - Membership, Court, and Booking operations
Owned by Nayan (Backend: Membership and Bookings)
Styled by Pratik (Frontend templates & styling)
"""

from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Member, MembershipPlan, Court, Booking, BookingParticipant
from .forms import MemberForm, BookingForm, BookingParticipantForm


def member_list(request):
    """
    Lists registered club members with their assigned plan and active status.
    Handoff to Pratik:
    - Route name: 'club:member_list'
    - Template path: 'club/members.html'
    - Context keys: 'page_title', 'members', 'plans'
    """
    members = Member.objects.select_related('plan').all()
    plans = MembershipPlan.objects.filter(active=True)
    form = MemberForm()

    context = {
        'page_title': 'Club Members',
        'members': members,
        'plans': plans,
        'form': form,
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

    bookings = Booking.objects.select_related('court', 'booked_by_member', 'booked_by_member__plan')

    if court_id:
        bookings = bookings.filter(court_id=court_id)
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    courts = Court.objects.filter(active=True)
    booking_form = BookingForm()

    context = {
        'page_title': 'Court Bookings',
        'bookings': bookings,
        'courts': courts,
        'selected_court': court_id,
        'selected_status': status_filter,
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
                for field, errors in err.message_dict.items():
                    for error in errors:
                        form.add_error(field if field != '__all__' else None, error)
                messages.error(request, "Booking validation failed. See errors below.")
            except Exception as exc:
                messages.error(request, f"Database constraint violation: {exc}")
        else:
            messages.error(request, "Please correct the errors in the booking form.")
    else:
        form = BookingForm()

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
                for field, errors in err.message_dict.items():
                    for error in errors:
                        participant_form.add_error(field if field != '__all__' else None, error)
                messages.error(request, "Participant validation failed.")

    context = {
        'page_title': f"Booking #{booking.id} Details",
        'booking': booking,
        'participants': participants,
        'participant_form': participant_form,
    }
    return render(request, 'club/booking_detail.html', context)
