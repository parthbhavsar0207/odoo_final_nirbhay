"""Guest-sale arithmetic and inventory validation, without database access."""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator


ZERO = Decimal("0.00")
CENT = Decimal("0.01")
MAX_QUANTITY = 2147483647


class InsufficientStock(ValidationError):
    def __init__(self, *, quantity, available):
        super().__init__(
            "Requested %(quantity)s units; only %(available)s available.",
            code="insufficient_stock",
            params={"quantity": quantity, "available": available},
        )


def validate_quantity(quantity):
    if type(quantity) is not int or not 1 <= quantity <= MAX_QUANTITY:
        raise ValidationError("Quantity must be a positive whole number.", code="invalid_quantity")


def _validate_available(available):
    if type(available) is not int or not 0 <= available <= MAX_QUANTITY:
        raise ValidationError("Inventory is outside its valid range.", code="invalid_stock")


def validate_stock(*, quantity, available, is_active=True):
    validate_quantity(quantity)
    _validate_available(available)
    if not is_active:
        raise ValidationError("Inactive products cannot be sold.", code="inactive_product")
    if quantity > available:
        raise InsufficientStock(quantity=quantity, available=available)


def restored_stock(*, quantity, available):
    """Validate a restock before writing; callers decide whether it is needed."""
    validate_quantity(quantity)
    _validate_available(available)
    restored = quantity + available
    _validate_available(restored)
    return restored


@dataclass(frozen=True)
class LineAmounts:
    unit_price: Decimal
    quantity: int
    subtotal: Decimal
    discount: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class SaleAmounts:
    subtotal: Decimal
    discount: Decimal
    total: Decimal


def calculate_guest_line(*, unit_price, quantity):
    validate_quantity(quantity)
    if not isinstance(unit_price, Decimal) or not unit_price.is_finite() or unit_price < ZERO:
        raise ValidationError("Price must be a finite nonnegative Decimal.", code="invalid_price")
    DecimalValidator(max_digits=10, decimal_places=2)(unit_price)
    with localcontext() as context:
        context.prec = 28
        subtotal = (unit_price * quantity).quantize(CENT)
    DecimalValidator(max_digits=14, decimal_places=2)(subtotal)
    # Guests have no membership discount. Do not guess plan rates or rounding.
    return LineAmounts(unit_price, quantity, subtotal, ZERO, subtotal)


def calculate_guest_totals(lines):
    lines = tuple(lines)
    if not lines:
        raise ValidationError("A sale must contain at least one item.", code="empty_sale")
    with localcontext() as context:
        context.prec = 28
        subtotal = sum((line.subtotal for line in lines), ZERO).quantize(CENT)
    DecimalValidator(max_digits=14, decimal_places=2)(subtotal)
    return SaleAmounts(subtotal, ZERO, subtotal)
