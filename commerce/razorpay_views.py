"""Actual Razorpay Test Mode checkout, with POST-only order and verification."""

import logging

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_safe

from .payment_views import _target, _return_url
from .razorpay_gateway import (
    RazorpayConfigurationError, RazorpayUnavailable, _payable_amount,
    amount_in_paise, create_test_order, test_client, verify_test_payment,
)


logger = logging.getLogger(__name__)


class RazorpayResponseForm(forms.Form):
    razorpay_order_id = forms.RegexField(r'^order_[A-Za-z0-9]{1,56}$', max_length=64)
    razorpay_payment_id = forms.RegexField(r'^pay_[A-Za-z0-9]{1,56}$', max_length=64)
    razorpay_signature = forms.RegexField(r'^[a-fA-F0-9]{64}$', max_length=64)


def _enabled():
    if not settings.RAZORPAY_TEST_MODE_ENABLED:
        raise Http404('Razorpay Test Mode is disabled.')


def _response(request, kind, pk, *, error_message=None, status=200):
    target = _target(kind, pk)
    amount = target.total if kind == 'sale' else target.price
    payable, config = False, None
    terminal = (
        target.status != 'draft' if kind == 'sale'
        else target.status != 'confirmed' or target.payment_status != 'pending'
    )
    if not terminal:
        try:
            amount = _payable_amount(kind, target)
            paise = amount_in_paise(amount)
            test_client()  # Configuration validation only; no provider request.
            if target.razorpay_order_id and (
                target.razorpay_order_amount != amount
                or target.razorpay_order_method != target.payment_method
            ):
                raise ValidationError('Order changed. Cancel it and create a new transaction.', code='stale_checkout')
            payable = True
            if target.razorpay_order_id:
                config = {
                    'key': settings.RAZORPAY_KEY_ID.strip(),
                    'order_id': target.razorpay_order_id, 'amount': paise,
                    'currency': 'INR', 'name': 'Champions Club',
                    'description': f'{kind.title()} #{pk} — TEST MODE',
                    'method': 'card' if target.payment_method == 'card' else 'upi',
                    'verify_url': reverse('commerce:razorpay_payment_verify', args=[kind, pk]),
                }
        except RazorpayConfigurationError as error:
            payable, error_message, status = False, str(error), 503
        except ValidationError as error:
            payable, error_message, status = False, ' '.join(error.messages), 409
    customer = bool(target.customer_id and request.user.is_authenticated and target.customer_id == request.user.pk)
    return render(request, 'customer/razorpay_payment.html' if customer else 'commerce/razorpay_payment.html', {
        'target_kind': kind, 'target_id': pk, 'target_label': f'{kind.title()} #{pk}',
        'amount': amount, 'payment_method_label': target.get_payment_method_display(),
        'return_url': _return_url(kind, pk, customer=customer), 'payable': payable,
        'error_message': error_message, 'checkout_config': config,
        'provider_reference': target.razorpay_payment_id,
        'payment_is_simulated': target.payment_is_simulated,
    }, status=status)


def _unavailable():
    logger.exception('Razorpay checkout database unavailable')
    return HttpResponse('Checkout is unavailable. Check the transaction before retrying.', status=503)


@require_safe
@never_cache
@ensure_csrf_cookie
def razorpay_payment(request, kind, pk):
    _enabled()
    try:
        return _response(request, kind, pk)
    except DatabaseError:
        return _unavailable()


@require_POST
@never_cache
@csrf_protect
def razorpay_order_create(request, kind, pk):
    _enabled()
    try:
        _target(kind, pk)
        try:
            create_test_order(kind, pk)
        except (RazorpayConfigurationError, RazorpayUnavailable) as error:
            return _response(request, kind, pk, error_message=str(error), status=503)
        except ValidationError as error:
            return _response(request, kind, pk, error_message=' '.join(error.messages), status=409)
    except DatabaseError:
        return _unavailable()
    return redirect('commerce:razorpay_payment', kind=kind, pk=pk)


@require_POST
@never_cache
@csrf_protect
def razorpay_payment_verify(request, kind, pk):
    _enabled()
    try:
        _target(kind, pk)
        form = RazorpayResponseForm(request.POST)
        if not form.is_valid():
            return _response(request, kind, pk, error_message='Invalid Razorpay checkout response.', status=400)
        try:
            target = verify_test_payment(kind=kind, pk=pk,
                order_id=form.cleaned_data['razorpay_order_id'],
                payment_id=form.cleaned_data['razorpay_payment_id'],
                signature=form.cleaned_data['razorpay_signature'],
            )
        except (RazorpayConfigurationError, RazorpayUnavailable) as error:
            return _response(request, kind, pk, error_message=str(error), status=503)
        except ValidationError as error:
            return _response(request, kind, pk, error_message=' '.join(error.messages), status=409)
    except DatabaseError:
        return _unavailable()
    messages.success(request, 'Razorpay test payment verified. No real money was charged.')
    return redirect(_return_url(kind, pk, customer=bool(target.customer_id and target.customer_id == request.user.pk)))
