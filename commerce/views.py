"""Commerce HTTP entry points; transactions and amounts stay in services."""

import logging

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_safe

from .counter_forms import GuestSaleForm, MemberSaleForm
from .models import Product, Sale
from .services import cancel_sale, complete_sale, create_guest_sale, create_sale


logger = logging.getLogger(__name__)


def shop_index(request):
    """
    Placeholder view for Club Shop & Bar point-of-sale catalog.
    Handoff to Pratik:
    - Route name: 'commerce:shop'
    - Template path: 'commerce/index.html'
    - Context keys: 'page_title', 'products'
    """
    context = {
        'page_title': 'Shop & Bar',
        'products': [],  # To be populated by Utkarsh once Product model is migrated
    }
    return render(request, 'commerce/index.html', context)


def _counter_response(request, *, form=None, sale=None, error_message=None, status=200, member_mode=False):
    """Reuse Pratik's existing template without introducing competing markup."""
    context = {
        "page_title": ("Member Counter" if member_mode else "Guest Counter") if sale is None else f"Sale #{sale.pk}",
        "products": Product.objects.filter(is_active=True),
        "form": (MemberSaleForm() if member_mode else GuestSaleForm()) if form is None else form,
        "sale": sale,
        "sale_items": sale.items.select_related("product").all() if sale is not None else [],
        "error_message": error_message,
        "member_mode": member_mode,
    }
    return render(request, "commerce/index.html", context, status=status)


@require_safe
@ensure_csrf_cookie
def guest_counter(request):
    return _counter_response(request)


@require_safe
@ensure_csrf_cookie
def member_counter(request):
    return _counter_response(request, member_mode=True)


@require_POST
@csrf_protect
def member_sale_create(request):
    form = MemberSaleForm(request.POST)
    try:
        if not form.is_valid():
            return _counter_response(request, form=form, member_mode=True, status=400)
        sale = create_sale(
            quantities={form.cleaned_data["product"].pk: form.cleaned_data["quantity"]},
            payment_method=form.cleaned_data["payment_method"],
            member_id=form.cleaned_data["member"].pk,
        )
    except ValidationError as error:
        form.add_error(None, error.messages)
        return _counter_response(request, form=form, member_mode=True, status=400)
    except DatabaseError:
        logger.exception("Member draft creation failed")
        return HttpResponse(
            "The sale could not be created. Check its status before trying again.",
            status=503, content_type="text/plain",
        )
    return redirect("commerce:sale_detail", pk=sale.pk)


@require_POST
@csrf_protect
def sale_create(request):
    form = GuestSaleForm(request.POST)
    try:
        if not form.is_valid():
            return _counter_response(request, form=form, status=400)
        sale = create_guest_sale(
            quantities={form.cleaned_data["product"].pk: form.cleaned_data["quantity"]},
            payment_method=form.cleaned_data["payment_method"],
        )
    except ValidationError as error:
        form.add_error(None, error.messages)
        return _counter_response(request, form=form, status=400)
    except DatabaseError:
        logger.exception("Guest draft creation failed")
        return HttpResponse(
            "The sale could not be created. Check its status before trying again.",
            status=503, content_type="text/plain",
        )
    return redirect("commerce:sale_detail", pk=sale.pk)


@require_safe
@ensure_csrf_cookie
def sale_detail(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    return _counter_response(request, sale=sale)


@require_safe
def sale_receipt(request, pk):
    """Clean printable thermal / standard POS receipt for completed or past counter sales."""
    sale = get_object_or_404(
        Sale.objects.select_related('member', 'member__plan').prefetch_related('items__product'),
        pk=pk
    )
    context = {
        'page_title': f"Receipt #{sale.pk} · Champions Club",
        'sale': sale,
        'items': sale.items.all(),
    }
    return render(request, "commerce/receipt.html", context)


def _sale_action(request, pk, operation):
    try:
        sale = operation(pk)
    except Sale.DoesNotExist as error:
        raise Http404("Sale does not exist.") from error
    except ValidationError as error:
        sale = get_object_or_404(Sale, pk=pk)
        return _counter_response(
            request, sale=sale, error_message=" ".join(error.messages), status=409,
        )
    except DatabaseError:
        logger.exception("Guest sale action failed for sale %s", pk)
        return HttpResponse(
            "The sale could not be updated. Check its status before trying again.",
            status=503, content_type="text/plain",
        )
    return redirect("commerce:sale_detail", pk=sale.pk)


@require_POST
@csrf_protect
def sale_complete(request, pk):
    return _sale_action(request, pk, complete_sale)


@require_POST
@csrf_protect
def sale_cancel(request, pk):
    return _sale_action(request, pk, cancel_sale)
