"""A local payment simulator, never a processor or a real payment callback."""

from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from club.models import Booking

from .models import Sale
from .services import complete_sale, quote_sale


def payment_target(kind, pk, *, lock=False):
    model = Sale if kind == 'sale' else Booking if kind == 'booking' else None
    if model is None:
        raise ValidationError('Unknown payment target.', code='invalid_target')
    queryset = model.objects.select_for_update() if lock else model.objects
    return queryset.get(pk=pk)


def payment_amount(kind, target):
    if kind == 'sale':
        return quote_sale(target.pk)
    if target.status != 'confirmed':
        raise ValidationError('Only confirmed reservations can be paid.', code='invalid_booking_state')
    return target.price


def simulate_payment(*, kind, pk, amount, payment_method, outcome):
    """Complete a simulated payment and its existing business mutation atomically.

    Failure/cancel outcomes never complete a sale or change its stock. Booking
    payment attempts leave the confirmed reservation pending until success.
    The expected amount/method come from a verified server-signed checkout.
    """
    if outcome not in {'success', 'failure', 'cancel'}:
        raise ValidationError('Choose a valid demo outcome.', code='invalid_outcome')
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
        raise ValidationError('Invalid checkout amount.', code='invalid_amount')
    with transaction.atomic():
        target = payment_target(kind, pk, lock=True)
        if target.razorpay_order_id:
            raise ValidationError(
                'This transaction has a Razorpay test order. Use its verified checkout.',
                code='provider_order_exists',
            )
        if target.payment_method != payment_method:
            raise ValidationError('Payment method changed. Open checkout again.', code='stale_checkout')
        if kind == 'sale':
            if target.payment_method not in {Sale.PaymentMethod.CARD, Sale.PaymentMethod.UPI}:
                raise ValidationError('Use the counter for cash payments.', code='invalid_payment_method')
            if target.status == Sale.Status.CANCELLED:
                raise ValidationError('Cancelled sales cannot be paid.', code='invalid_sale_state')
            if target.status == Sale.Status.COMPLETED:
                if target.payment_is_simulated and target.total == amount:
                    return target, 'already_successful'
                raise ValidationError('This sale is already completed.', code='already_completed')
            if quote_sale(target.pk) != amount:
                raise ValidationError('Price or benefits changed. Review checkout again.', code='stale_checkout')
        else:
            if target.payment_method not in {Booking.PaymentMethod.CARD, Booking.PaymentMethod.UPI}:
                raise ValidationError('This reservation does not require electronic checkout.', code='invalid_payment_method')
            if target.status != 'confirmed':
                raise ValidationError('Cancelled or draft reservations cannot be paid.', code='invalid_booking_state')
            if target.price != amount:
                raise ValidationError('Reservation amount changed. Open checkout again.', code='stale_checkout')
            if amount == 0:
                raise ValidationError('This reservation does not require payment.', code='invalid_payment_state')
            if target.payment_status == Booking.PaymentStatus.PAID:
                if target.payment_is_simulated:
                    return target, 'already_successful'
                raise ValidationError('This reservation is already marked paid.', code='already_paid')
            if target.payment_status != Booking.PaymentStatus.PENDING:
                raise ValidationError('This reservation does not require payment.', code='invalid_payment_state')

        if outcome != 'success':
            return target, outcome
        reference = 'DEMO-' + uuid4().hex
        if kind == 'sale':
            target = complete_sale(target.pk)
            if target.total != amount:
                # Includes any changed quote between checks; atomic rolls back
                # deductions, snapshots and status together.
                raise ValidationError('Price changed. Review checkout again.', code='stale_checkout')
            target.payment_is_simulated = True
            target.demo_payment_reference = reference
            target.save(update_fields=['payment_is_simulated', 'demo_payment_reference'])
        else:
            # Do not reprice/reconfirm a historical booking merely to record the
            # simulated result. Row lock protects retries and cancellation.
            Booking.objects.filter(pk=target.pk).update(
                payment_status=Booking.PaymentStatus.PAID,
                payment_is_simulated=True, demo_payment_reference=reference,
                updated_at=timezone.now(),
            )
            target.refresh_from_db()
        return target, 'success'
