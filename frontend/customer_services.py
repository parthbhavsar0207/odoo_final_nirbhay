"""Customer workflows reuse shared commerce and booking database rules."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from club.models import Member, Booking
from commerce.models import Sale
from commerce.services import create_sale, cancel_sale
from .models import CustomerAccount


def account_for(user):
    return CustomerAccount.objects.select_related('member', 'member__plan').get_or_create(user=user)[0]


def create_customer_sale(user, *, product, quantity, payment_method):
    with transaction.atomic():
        account = account_for(user)
        sale = create_sale(quantities={product.pk: quantity}, payment_method=payment_method,
                           member_id=account.member_id)
        sale.customer = user
        sale.save(update_fields=['customer'])
        return sale


def create_customer_booking(user, *, court, start_datetime, payment_method):
    with transaction.atomic():
        account = account_for(user)
        member = Member.objects.select_for_update().get(pk=account.member_id) if account.member_id else None
        booking = Booking(customer=user, court=court, booked_by_member=member,
                          walkin_name='' if member else (user.first_name or user.get_username()),
                          walkin_contact='' if member else user.email,
                          start_datetime=start_datetime, status='confirmed', booking_type='standard',
                          payment_method=payment_method, payment_status=Booking.PaymentStatus.PENDING)
        booking.price = booking.calculate_price()
        if booking.price == Decimal('0.00'):
            booking.payment_status = Booking.PaymentStatus.WAIVED
        booking.save()  # Existing save locks roster, snapshots price, validates and creates participant.
        return booking


def cancel_customer_sale(user, pk):
    with transaction.atomic():
        sale = Sale.objects.select_for_update().get(pk=pk, customer=user)
        if sale.status == Sale.Status.COMPLETED:
            raise ValidationError('Contact the club for a return or refund. Completed purchases cannot be cancelled here.')
        return cancel_sale(pk)


def cancel_customer_booking(user, pk):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=pk, customer=user)
        if booking.status == 'cancelled':
            return booking
        if booking.payment_status == Booking.PaymentStatus.PAID:
            raise ValidationError('Contact the club to cancel a paid reservation and arrange any refund.')
        booking.status = 'cancelled'
        booking.save()
        return booking
