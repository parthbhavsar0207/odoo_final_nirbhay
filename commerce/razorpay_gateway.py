"""Razorpay TEST orders and verified payment completion on existing records."""

from decimal import Decimal
import re
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
import razorpay
import requests

from club.models import Booking
from .demo_gateway import payment_target
from .models import Sale
from .services import complete_sale, quote_sale


class RazorpayConfigurationError(Exception):
    pass


class RazorpayUnavailable(Exception):
    pass


class TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', (3.05, 10))
        return super().request(method, url, **kwargs)


def test_client():
    """Only allow a configured test key; never expose the private secret."""
    if not settings.RAZORPAY_TEST_MODE_ENABLED:
        raise RazorpayConfigurationError('Razorpay Test Mode is disabled.')
    key = settings.RAZORPAY_KEY_ID.strip()
    secret = settings.RAZORPAY_KEY_SECRET.strip()
    if not key or not secret:
        raise RazorpayConfigurationError(
            'Razorpay test keys are not configured. Add RAZORPAY_KEY_ID and '
            'RAZORPAY_KEY_SECRET to the local .env, then restart Django.'
        )
    if not key.startswith('rzp_test_'):
        raise RazorpayConfigurationError('Only rzp_test_ keys are allowed. Live payments are disabled.')
    return razorpay.Client(auth=(key, secret), session=TimeoutSession())


def _provider_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except (requests.RequestException, razorpay.errors.BadRequestError,
            razorpay.errors.GatewayError, razorpay.errors.ServerError, ValueError) as error:
        # Provider exceptions may contain private details. Return generic text.
        raise RazorpayUnavailable(
            'Razorpay Test Mode is unavailable. Check the transaction and retry.'
        ) from error


def amount_in_paise(amount):
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
        raise ValidationError('This transaction does not require payment.', code='invalid_amount')
    paise = amount * 100
    if paise != paise.to_integral_value():
        raise ValidationError('The amount must have two decimal places.', code='invalid_amount')
    return int(paise)


def _identifier(value, prefix):
    return isinstance(value, str) and bool(re.fullmatch(prefix + r'_[A-Za-z0-9]{1,56}', value))


def _payable_amount(kind, target):
    method = target.payment_method
    electronic = {Sale.PaymentMethod.CARD, Sale.PaymentMethod.UPI} if kind == 'sale' else {Booking.PaymentMethod.CARD, Booking.PaymentMethod.UPI}
    if method not in electronic:
        raise ValidationError('Choose card or UPI for Razorpay Test Mode.', code='invalid_payment_method')
    if kind == 'sale':
        if target.status != Sale.Status.DRAFT:
            raise ValidationError('Only draft sales can enter checkout.', code='invalid_sale_state')
        return quote_sale(target.pk)
    if target.status != 'confirmed' or target.payment_status != Booking.PaymentStatus.PENDING:
        raise ValidationError('Only confirmed, unpaid reservations can enter checkout.', code='invalid_booking_state')
    return target.price


def create_test_order(kind, pk):
    """One persisted order per transaction. GET never calls this service.

    Keep the parent lock across the bounded provider request to serialize local
    duplicate POSTs. Stock is checked, but not reserved. A provider timeout may
    leave an unused remote order; no payment is recorded from that uncertainty.
    """
    client = test_client()
    with transaction.atomic():
        target = payment_target(kind, pk, lock=True)
        amount = _payable_amount(kind, target)
        paise = amount_in_paise(amount)
        if target.razorpay_order_id:
            if target.razorpay_order_amount != amount or target.razorpay_order_method != target.payment_method:
                raise ValidationError(
                    'This order has changed. Cancel it and create a new transaction; '
                    'do not pay the old checkout.', code='stale_checkout',
                )
            return target
        order = _provider_call(client.order.create, data={
            'amount': paise, 'currency': 'INR', 'partial_payment': False,
            'receipt': f'cc-{kind}-{pk}-{uuid4().hex[:8]}',
            'notes': {'target_kind': kind, 'target_id': str(pk), 'mode': 'test'},
        })
        if (not isinstance(order, dict) or not _identifier(order.get('id'), 'order')
                or type(order.get('amount')) is not int or order['amount'] != paise
                or order.get('currency') != 'INR'):
            raise RazorpayUnavailable('Razorpay returned an unexpected test order. No local payment recorded.')
        target.razorpay_order_id = order['id']
        target.razorpay_order_amount = amount
        target.razorpay_order_method = target.payment_method
        target.save(update_fields=['razorpay_order_id', 'razorpay_order_amount', 'razorpay_order_method'])
        return target


def verify_test_payment(*, kind, pk, order_id, payment_id, signature):
    """Verify signature AND provider capture, then mutate existing business rows.

    This boundary uses the saved server order ID, never a caller-selected order.
    A signed browser success alone cannot deduct inventory or mark a booking paid.
    """
    client = test_client()
    if (not _identifier(order_id, 'order') or not _identifier(payment_id, 'pay')
            or not isinstance(signature, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', signature)):
        raise ValidationError('Invalid Razorpay payment response.', code='invalid_payment')
    with transaction.atomic():
        target = payment_target(kind, pk, lock=True)
        if not target.razorpay_order_id or order_id != target.razorpay_order_id:
            raise ValidationError('Payment does not belong to this saved order.', code='invalid_order')
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': target.razorpay_order_id,
                'razorpay_payment_id': payment_id, 'razorpay_signature': signature,
            })
        except razorpay.errors.SignatureVerificationError as error:
            raise ValidationError('Razorpay payment signature could not be verified.', code='invalid_signature') from error
        terminal = target.status == Sale.Status.COMPLETED if kind == 'sale' else target.status == 'confirmed' and target.payment_status == Booking.PaymentStatus.PAID
        if target.razorpay_payment_id:
            if terminal and target.razorpay_payment_id == payment_id:
                return target
            raise ValidationError('This transaction is already paid or cancelled.', code='invalid_payment_state')
        amount = _payable_amount(kind, target)
        if target.razorpay_order_amount != amount or target.razorpay_order_method != target.payment_method:
            raise ValidationError('The order amount or method changed. Payment cannot be applied.', code='stale_checkout')
        paise = amount_in_paise(amount)
        payment = _provider_call(client.payment.fetch, payment_id)
        expected_method = 'card' if target.payment_method == 'card' else 'upi'
        if (not isinstance(payment, dict) or payment.get('id') != payment_id
                or payment.get('order_id') != target.razorpay_order_id
                or type(payment.get('amount')) is not int or payment['amount'] != paise
                or payment.get('currency') != 'INR' or payment.get('method') != expected_method
                or payment.get('status') != 'captured' or payment.get('captured') is not True
                or payment.get('amount_refunded', 0) != 0):
            raise ValidationError(
                'Razorpay has not confirmed the expected captured test payment. '
                'Check payment capture in your Test Mode dashboard; no local completion occurred.',
                code='unconfirmed_payment',
            )
        if kind == 'sale':
            target = complete_sale(target.pk, verified_razorpay_order_id=order_id)
            if target.total != amount:
                raise ValidationError('Price changed. Payment could not be applied.', code='stale_checkout')
        else:
            Booking.objects.filter(pk=target.pk).update(
                payment_status=Booking.PaymentStatus.PAID, updated_at=timezone.now(),
            )
            target.refresh_from_db()
        target.razorpay_payment_id = payment_id
        target.payment_is_simulated = True
        target.save(update_fields=['razorpay_payment_id', 'payment_is_simulated'])
        return target
