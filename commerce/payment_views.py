"""CSRF-protected, server-priced simulated checkout for sales and bookings."""

import logging
import secrets
from decimal import Decimal, InvalidOperation

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_safe

from club.models import Booking

from .demo_gateway import payment_amount, payment_target, simulate_payment
from .models import Sale


logger = logging.getLogger(__name__)
SALT = 'champions-club-demo-checkout-v1'
CHECKOUT_MAX_AGE = 600


class DemoPaymentForm(forms.Form):
    checkout_token = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    outcome = forms.ChoiceField(choices=[
        ('success', 'Success'), ('failure', 'Failure'), ('cancel', 'Cancel'),
    ])


def _enabled():
    if not settings.DEMO_PAYMENT_GATEWAY_ENABLED:
        raise Http404('Payment simulator is disabled.')


def _target(kind, pk):
    if kind not in {'sale', 'booking'}:
        raise Http404('Payment target does not exist.')
    try:
        return payment_target(kind, pk)
    except (Sale.DoesNotExist, Booking.DoesNotExist) as error:
        raise Http404('Payment target does not exist.') from error


def _return_url(kind, pk, *, customer=False):
    if customer:
        return reverse('customer:sale_detail' if kind == 'sale' else 'customer:booking_detail', args=[pk])
    return reverse('commerce:sale_detail' if kind == 'sale' else 'club:booking_detail', args=[pk])


def _nonce(request):
    if 'demo_checkout_nonce' not in request.session:
        request.session['demo_checkout_nonce'] = secrets.token_hex(24)
    return request.session['demo_checkout_nonce']


def _checkout_response(request, kind, pk, *, error_message=None, status=200):
    target = _target(kind, pk)
    terminal = (
        target.status in {'completed', 'cancelled'} if kind == 'sale'
        else target.status != 'confirmed' or target.payment_status != 'pending'
    )
    payable = not terminal and target.payment_method in {'card', 'UPI', 'upi'}
    if kind == 'booking' and target.price <= 0:
        payable = False
    amount = target.total if kind == 'sale' else target.price
    token = None
    if payable:
        try:
            amount = payment_amount(kind, target)
        except ValidationError as error:
            error_message = ' '.join(error.messages)
            payable = False
            status = 409
        else:
            token = signing.dumps({
                'kind': kind, 'pk': pk, 'amount': str(amount),
                'method': target.payment_method, 'nonce': _nonce(request),
            }, salt=SALT)
    customer = bool(target.customer_id and request.user.is_authenticated and target.customer_id == request.user.pk)
    return render(request, 'customer/demo_payment.html' if customer else 'commerce/demo_payment.html', {
        'target_kind': kind, 'target_id': pk,
        'target_label': ('Sale' if kind == 'sale' else 'Court booking') + f' #{pk}',
        'payment_method': target.payment_method,
        'payment_method_label': target.get_payment_method_display(),
        'amount': amount, 'checkout_token': token, 'payable': payable,
        'return_url': _return_url(kind, pk, customer=customer), 'error_message': error_message,
        'payment_reference': target.demo_payment_reference,
        'payment_is_simulated': target.payment_is_simulated,
    }, status=status)


@require_safe
@never_cache
@ensure_csrf_cookie
def demo_payment(request, kind, pk):
    _enabled()
    try:
        return _checkout_response(request, kind, pk)
    except DatabaseError:
        logger.exception('Demo payment quote failed')
        return HttpResponse('Checkout is temporarily unavailable.', status=503)


def _payment_submission(request, kind, pk):
    _target(kind, pk)
    form = DemoPaymentForm(request.POST)
    if not form.is_valid():
        return _checkout_response(request, kind, pk, error_message='Choose a valid demo outcome.', status=400)
    try:
        payload = signing.loads(
            form.cleaned_data['checkout_token'], salt=SALT, max_age=CHECKOUT_MAX_AGE,
        )
        if (
            not isinstance(payload, dict)
            or payload.get('kind') != kind or payload.get('pk') != pk
            or not isinstance(payload.get('amount'), str)
            or not isinstance(payload.get('method'), str)
            or not request.session.get('demo_checkout_nonce')
            or payload.get('nonce') != request.session.get('demo_checkout_nonce')
        ):
            raise signing.BadSignature('Checkout does not match this session/transaction.')
        amount = Decimal(payload['amount'])
        target, result = simulate_payment(
            kind=kind, pk=pk, amount=amount, payment_method=payload['method'],
            outcome=form.cleaned_data['outcome'],
        )
    except (signing.BadSignature, KeyError, InvalidOperation):
        return _checkout_response(request, kind, pk, error_message='Checkout expired or is invalid. Review the new amount and retry.', status=400)
    except ValidationError as error:
        return _checkout_response(request, kind, pk, error_message=' '.join(error.messages), status=409)
    if result in {'success', 'already_successful'}:
        messages.success(request, 'Simulated payment successful. No real money was charged.')
        return redirect(_return_url(kind, pk, customer=bool(target.customer_id and target.customer_id == request.user.pk)))
    if result == 'failure':
        return _checkout_response(request, kind, pk, error_message='Simulated payment failed. No money was charged; you can retry.', status=200)
    messages.info(request, 'Simulated payment cancelled. No money was charged; transaction remains unpaid.')
    return redirect(_return_url(kind, pk, customer=bool(target.customer_id and target.customer_id == request.user.pk)))


@require_POST
@never_cache
@csrf_protect
def demo_payment_submit(request, kind, pk):
    _enabled()
    try:
        return _payment_submission(request, kind, pk)
    except (Sale.DoesNotExist, Booking.DoesNotExist) as error:
        raise Http404('Payment target does not exist.') from error
    except DatabaseError:
        # Also cover initial target lookup and error-page rendering. Do not
        # query the database again to render an unavailable response.
        logger.exception('Demo payment submission unavailable')
        return HttpResponse(
            'Payment simulator is temporarily unavailable. Check the transaction before retrying.',
            status=503,
        )
