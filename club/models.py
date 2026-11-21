"""
Club App Models (Owned by Nayan)

Models to be implemented by Nayan:
- MembershipPlan: tier (gold, silver, junior), court entitlement/pricing, shop discount, bar discount, active status
- Member: name, contact, plan FK, start_date, end_date, suspended flag (single identity for bookings & commerce)
- Court: name, sport, capacity, active status
- Booking: court FK, optional booked_by_member FK (walk-ins have None), start_datetime, end_datetime, status, type, price snapshot
- BookingParticipant: booking FK, optional member FK, guest name
"""

from django.db import models

# Nayan will implement the core models in the agreed build order:
# 1. MembershipPlan, Member, Court
# 2. Booking, BookingParticipant (with PostgreSQL GiST exclusion constraint for no-overlap)
