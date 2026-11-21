"""Database-free guest rules; these do not prove transaction/locking behavior."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from commerce.calculations import (
    MAX_QUANTITY,
    InsufficientStock,
    calculate_guest_line,
    calculate_guest_totals,
    restored_stock,
    validate_quantity,
    validate_stock,
)
from commerce.models import Sale, SaleItem
from commerce.services import (
    cancellation_requires_restock,
    completion_required,
    create_guest_sale,
)


class GuestCalculationTests(SimpleTestCase):
    def test_decimal_multiplication_is_exact(self):
        line = calculate_guest_line(unit_price=Decimal("0.10"), quantity=3)
        self.assertEqual(line.line_total, Decimal("0.30"))
        self.assertIsInstance(line.line_total, Decimal)

    def test_guest_lines_have_zero_discount(self):
        line = calculate_guest_line(unit_price=Decimal("12.50"), quantity=2)
        self.assertEqual(line.discount, Decimal("0.00"))
        self.assertEqual(line.subtotal, Decimal("25.00"))

    def test_multiple_lines_sum_without_floats(self):
        totals = calculate_guest_totals([
            calculate_guest_line(unit_price=Decimal("12.50"), quantity=2),
            calculate_guest_line(unit_price=Decimal("0.10"), quantity=2),
        ])
        self.assertEqual(totals.subtotal, Decimal("25.20"))
        self.assertEqual(totals.discount, Decimal("0.00"))
        self.assertEqual(totals.total, Decimal("25.20"))

    def test_zero_price_is_valid(self):
        line = calculate_guest_line(unit_price=Decimal("0.00"), quantity=2)
        self.assertEqual(line.line_total, Decimal("0.00"))

    def test_invalid_prices_are_rejected(self):
        for price in [0.1, "1.00", Decimal("NaN"), Decimal("Infinity"), Decimal("-0.01")]:
            with self.subTest(price=price), self.assertRaises(ValidationError):
                calculate_guest_line(unit_price=price, quantity=1)

    def test_price_precision_and_size_are_validated(self):
        for price in [Decimal("1.001"), Decimal("100000000.00")]:
            with self.subTest(price=price), self.assertRaises(ValidationError):
                calculate_guest_line(unit_price=price, quantity=1)

    def test_quantities_must_be_positive_whole_integers(self):
        for quantity in [0, -1, 1.5, Decimal("1.5"), "2", True, MAX_QUANTITY + 1]:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                validate_quantity(quantity)

    def test_maximum_quantity_is_valid_when_amount_fits(self):
        line = calculate_guest_line(unit_price=Decimal("0.01"), quantity=MAX_QUANTITY)
        self.assertEqual(line.line_total, Decimal("21474836.47"))

    def test_oversized_line_total_is_rejected_before_storage(self):
        with self.assertRaises(ValidationError):
            calculate_guest_line(unit_price=Decimal("99999999.99"), quantity=10001)

    def test_oversized_sale_total_is_rejected_before_storage(self):
        line = calculate_guest_line(unit_price=Decimal("99999999.99"), quantity=10000)
        with self.assertRaises(ValidationError):
            calculate_guest_totals([line, line])

    def test_empty_sale_is_rejected(self):
        with self.assertRaises(ValidationError):
            calculate_guest_totals([])


class GuestInventoryRuleTests(SimpleTestCase):
    def test_insufficient_stock_has_specific_error(self):
        with self.assertRaises(InsufficientStock) as error:
            validate_stock(quantity=3, available=2)
        self.assertEqual(error.exception.code, "insufficient_stock")

    def test_exact_available_stock_is_allowed(self):
        validate_stock(quantity=2, available=2)

    def test_zero_stock_cannot_supply_one_item(self):
        with self.assertRaises(InsufficientStock):
            validate_stock(quantity=1, available=0)

    def test_inactive_products_cannot_be_sold(self):
        with self.assertRaises(ValidationError) as error:
            validate_stock(quantity=1, available=10, is_active=False)
        self.assertEqual(error.exception.code, "inactive_product")

    def test_invalid_available_inventory_is_rejected(self):
        for available in [-1, 1.5, True, MAX_QUANTITY + 1]:
            with self.subTest(available=available), self.assertRaises(ValidationError):
                validate_stock(quantity=1, available=available)

    def test_restoration_adds_original_quantity(self):
        self.assertEqual(restored_stock(quantity=2, available=3), 5)

    def test_restoration_rejects_integer_overflow(self):
        with self.assertRaises(ValidationError):
            restored_stock(quantity=1, available=MAX_QUANTITY)


class GuestSaleStateTests(SimpleTestCase):
    def test_draft_completion_requires_stock_deduction(self):
        self.assertTrue(completion_required(Sale.Status.DRAFT))

    def test_repeated_completed_status_requires_no_deduction(self):
        self.assertFalse(completion_required(Sale.Status.COMPLETED))

    def test_cancelled_sale_cannot_be_completed(self):
        with self.assertRaises(ValidationError):
            completion_required(Sale.Status.CANCELLED)

    def test_draft_cancellation_does_not_restore_stock(self):
        self.assertFalse(cancellation_requires_restock(Sale.Status.DRAFT))

    def test_completed_cancellation_requires_restoration(self):
        self.assertTrue(cancellation_requires_restock(Sale.Status.COMPLETED))

    def test_repeated_cancellation_requires_no_restoration(self):
        self.assertFalse(cancellation_requires_restock(Sale.Status.CANCELLED))

    def test_unknown_status_fails_closed(self):
        for rule in [completion_required, cancellation_requires_restock]:
            with self.subTest(rule=rule.__name__), self.assertRaises(ValidationError):
                rule("unknown")

    def test_invalid_draft_quantities_fail_before_database_access(self):
        for quantities in [{}, {1: 0}, {1: 1.5}, {True: 1}, {"1": 1}]:
            with self.subTest(quantities=quantities), self.assertRaises(ValidationError):
                create_guest_sale(quantities=quantities, payment_method=Sale.PaymentMethod.CASH)

    def test_unknown_payment_fails_before_database_access(self):
        with self.assertRaises(ValidationError):
            create_guest_sale(quantities={1: 1}, payment_method="bitcoin")


class GuestSaleModelValidationTests(SimpleTestCase):
    def validate_sale(self, **overrides):
        values = {"payment_method": Sale.PaymentMethod.CASH}
        values.update(overrides)
        sale = Sale(**values)
        sale.full_clean(
            exclude=["created_at"], validate_unique=False, validate_constraints=False,
        )
        return sale

    def test_new_sale_is_a_zero_total_draft(self):
        sale = self.validate_sale()
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(sale.total, Decimal("0.00"))

    def test_all_contract_payment_methods_validate(self):
        for method in ["cash", "card", "UPI"]:
            with self.subTest(method=method):
                self.validate_sale(payment_method=method)

    def test_unknown_status_and_payment_are_rejected(self):
        for values in [{"status": "paid"}, {"payment_method": "upi"}]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.validate_sale(**values)

    def test_negative_sale_amounts_are_rejected(self):
        for field in ["subtotal", "discount", "total"]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.validate_sale(**{field: Decimal("-0.01")})

    def test_item_requires_positive_quantity(self):
        item = SaleItem(sale_id=1, product_id=1, quantity=0)
        with self.assertRaises(ValidationError) as error:
            item.full_clean(
                exclude=["sale", "product"], validate_unique=False, validate_constraints=False,
            )
        self.assertIn("quantity", error.exception.message_dict)
