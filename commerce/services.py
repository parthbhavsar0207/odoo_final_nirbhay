"""The write interface for counter sales. All sale mutations use services."""

from collections.abc import Mapping

from django.core.exceptions import ValidationError
from django.db import NotSupportedError, connection, transaction
from django.db.models import F
from django.utils import timezone

from club.models import Member, MembershipPlan

from .calculations import (
    InsufficientStock,
    ZERO,
    calculate_sale_line,
    calculate_sale_totals,
    restored_stock,
    validate_quantity,
    validate_stock,
)
from .models import Product, Sale, SaleItem


def completion_required(status):
    """A completed sale is an idempotent retry; a cancelled sale cannot reopen."""
    if status == Sale.Status.DRAFT:
        return True
    if status == Sale.Status.COMPLETED:
        return False
    raise ValidationError("Only draft sales can be completed.", code="invalid_sale_state")


def cancellation_requires_restock(status):
    if status == Sale.Status.COMPLETED:
        return True
    if status in (Sale.Status.DRAFT, Sale.Status.CANCELLED):
        return False
    raise ValidationError("Unknown sale status.", code="invalid_sale_state")


def _require_postgresql():
    if connection.vendor != "postgresql" or not connection.features.has_select_for_update:
        raise NotSupportedError("Sale services require PostgreSQL row locking.")


def _normalise_quantities(quantities):
    if not isinstance(quantities, Mapping) or not quantities:
        raise ValidationError("Supply a nonempty product-ID to quantity mapping.", code="empty_sale")
    result = dict(quantities)
    for product_id, quantity in result.items():
        if type(product_id) is not int or product_id < 1:
            raise ValidationError("Product IDs must be positive integers.", code="invalid_product")
        validate_quantity(quantity)
    return result


def create_guest_sale(*, quantities, payment_method):
    """Preserve the existing guest interface with no member benefits."""
    return create_sale(quantities=quantities, payment_method=payment_method)


def create_sale(*, quantities, payment_method, member_id=None):
    """Create a draft without reserving stock or accepting caller-supplied prices."""
    quantities = _normalise_quantities(quantities)
    if payment_method not in Sale.PaymentMethod.values:
        raise ValidationError("Choose cash, card or UPI.", code="invalid_payment_method")
    if member_id is not None and (type(member_id) is not int or member_id < 1):
        raise ValidationError("Choose an existing member.", code="invalid_member")
    _require_postgresql()
    with transaction.atomic():
        if member_id is not None and not Member.objects.filter(pk=member_id).exists():
            raise ValidationError("Member does not exist.", code="invalid_member")
        products = list(Product.objects.filter(pk__in=quantities).order_by("pk"))
        if {product.pk for product in products} != set(quantities):
            raise ValidationError("One or more products do not exist.", code="invalid_product")
        if any(not product.is_active for product in products):
            raise ValidationError("Inactive products cannot be sold.", code="inactive_product")
        sale = Sale.objects.create(payment_method=payment_method, member_id=member_id)
        SaleItem.objects.bulk_create([
            SaleItem(sale=sale, product=product, quantity=quantities[product.pk])
            for product in products
        ])
        return sale


def _locked_items_and_products(sale):
    items = list(
        SaleItem.objects.select_for_update().filter(sale=sale).order_by("product_id")
    )
    if not items:
        raise ValidationError("A sale must contain at least one item.", code="empty_sale")
    products = {
        product.pk: product
        for product in Product.objects.select_for_update().filter(
            pk__in=[item.product_id for item in items]
        ).order_by("pk")
    }
    if len(products) != len(items):
        raise ValidationError("Sale products are inconsistent.", code="invalid_product")
    return items, products


def complete_sale(sale_id):
    """Snapshot prices/benefits and deduct stock once in one transaction."""
    _require_postgresql()
    with transaction.atomic():
        sale = Sale.objects.select_for_update().get(pk=sale_id)
        if not completion_required(sale.status):
            return sale
        if sale.payment_method not in Sale.PaymentMethod.values:
            raise ValidationError("Choose cash, card or UPI.", code="invalid_payment_method")
        # Lock separate queries: a nullable member/plan outer join cannot be
        # locked safely by PostgreSQL. Retry returns above before repricing.
        plan = None
        if sale.member_id is not None:
            member = Member.objects.select_for_update().get(pk=sale.member_id)
            if member.plan_id is not None:
                candidate = MembershipPlan.objects.select_for_update().get(pk=member.plan_id)
                if (
                    member.is_club_member
                    and member.is_active_on_date(timezone.localdate())
                    and candidate.active
                ):
                    plan = candidate
        items, products = _locked_items_and_products(sale)
        amounts = []
        for item in items:
            product = products[item.product_id]
            validate_stock(
                quantity=item.quantity,
                available=product.stock_quantity,
                is_active=product.is_active,
            )
            rate = ZERO
            if plan is not None:
                rate = (
                    plan.shop_discount_percent if product.category == Product.Category.SHOP
                    else plan.bar_discount_percent
                )
            amounts.append(calculate_sale_line(
                unit_price=product.price, quantity=item.quantity, discount_percent=rate,
            ))
        totals = calculate_sale_totals(amounts)

        # Validate every line before any deduction. Conditional F updates are an
        # additional guard; row locks serialize competing checkout services.
        for item, line in zip(items, amounts):
            updated = Product.objects.filter(
                pk=item.product_id, stock_quantity__gte=item.quantity,
            ).update(stock_quantity=F("stock_quantity") - item.quantity)
            if updated != 1:
                raise InsufficientStock(
                    quantity=item.quantity, available=products[item.product_id].stock_quantity,
                )
            item.unit_price = line.unit_price
            item.discount = line.discount
            item.line_total = line.line_total
        SaleItem.objects.bulk_update(items, ["unit_price", "discount", "line_total"])
        sale.subtotal = totals.subtotal
        sale.discount = totals.discount
        sale.total = totals.total
        sale.status = Sale.Status.COMPLETED
        sale.save(update_fields=["subtotal", "discount", "total", "status"])
        return sale


def cancel_sale(sale_id):
    """Keep snapshots for audit; restore completed-sale stock at most once."""
    _require_postgresql()
    with transaction.atomic():
        sale = Sale.objects.select_for_update().get(pk=sale_id)
        if sale.status == Sale.Status.CANCELLED:
            return sale
        if cancellation_requires_restock(sale.status):
            items, products = _locked_items_and_products(sale)
            for item in items:
                restored_stock(
                    quantity=item.quantity, available=products[item.product_id].stock_quantity,
                )
            for item in items:
                Product.objects.filter(pk=item.product_id).update(
                    stock_quantity=F("stock_quantity") + item.quantity,
                )
        sale.status = Sale.Status.CANCELLED
        sale.save(update_fields=["status"])
        return sale
