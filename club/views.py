"""
Club Views (Backend owned by Nayan, Frontend styled by Pratik)
"""

from django.shortcuts import render


def member_list(request):
    """
    Placeholder view for listing and managing club members.
    Handoff to Pratik:
    - Route name: 'club:member_list'
    - Template path: 'club/members.html'
    - Context keys: 'page_title', 'members'
    """
    context = {
        'page_title': 'Club Members',
        'members': [],  # To be populated by Nayan once Member model is migrated
    }
    return render(request, 'club/members.html', context)


def booking_list(request):
    """
    Placeholder view for court booking schedule and reservation.
    Handoff to Pratik:
    - Route name: 'club:booking_list'
    - Template path: 'club/bookings.html'
    - Context keys: 'page_title', 'bookings'
    """
    context = {
        'page_title': 'Court Bookings',
        'bookings': [],  # To be populated by Nayan once Booking model is migrated
    }
    return render(request, 'club/bookings.html', context)
