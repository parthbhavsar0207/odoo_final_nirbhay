"""The write interface for guest sales. All sale mutations must use services."""

from collections.abc import Mapping

from django.core.exceptions import ValidationError
from django.db import NotSupportedError, connection, transaction
from django.db.models import F

from .calculations import (
    InsufficientStock,
    calculate_guest_line,
    calculate_guest_totals,
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
        raise NotSupportedError("Guest sale services require PostgreSQL row locking.")


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
    """Create a draft without reserving stock or accepting caller-supplied prices."""
    quantities = _normalise_quantities(quantities)
    if payment_method not in Sale.PaymentMethod.values:
        raise ValidationError("Choose cash, card or UPI.", code="invalid_payment_method")
    _require_postgresql()
    with transaction.atomic():
        products = list(Product.objects.filter(pk__in=quantities).order_by("pk"))
        if {product.pk for product in products} != set(quantities):
            raise ValidationError("One or more products do not exist.", code="invalid_product")
        if any(not product.is_active for product in products):
            raise ValidationError("Inactive products cannot be sold.", code="inactive_product")
        sale = Sale.objects.create(payment_method=payment_method)
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
    """Snapshot guest prices and deduct stock once, in one PostgreSQL transaction."""
    _require_postgresql()
    with transaction.atomic():
        sale = Sale.objects.select_for_update().get(pk=sale_id)
        if not completion_required(sale.status):
            return sale
        if sale.payment_method not in Sale.PaymentMethod.values:
            raise ValidationError("Choose cash, card or UPI.", code="invalid_payment_method")
        items, products = _locked_items_and_products(sale)
        amounts = []
        for item in items:
            product = products[item.product_id]
            validate_stock(
                quantity=item.quantity,
                available=product.stock_quantity,
                is_active=product.is_active,
            )
            amounts.append(calculate_guest_line(unit_price=product.price, quantity=item.quantity))
        totals = calculate_guest_totals(amounts)

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
