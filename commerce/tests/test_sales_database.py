"""Real PostgreSQL guest-sale integration tests; never replace with ORM mocks."""

from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from commerce.calculations import MAX_QUANTITY, InsufficientStock
from commerce.models import Product, Sale, SaleItem
from commerce.services import cancel_sale, complete_sale, create_guest_sale


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL row locking")
class GuestSaleDatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shop = Product.objects.create(
            name="Tennis ball", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )
        cls.bar = Product.objects.create(
            name="Refreshment", category="bar", price=Decimal("0.10"), stock_quantity=2,
        )

    def draft(self, quantities=None):
        return create_guest_sale(
            quantities=quantities if quantities is not None else {self.shop.pk: 2},
            payment_method=Sale.PaymentMethod.CASH,
        )

    def test_draft_does_not_reserve_stock_or_snapshot_prices(self):
        sale = self.draft()
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(sale.items.get().unit_price, Decimal("0.00"))

    def test_completion_snapshots_prices_and_deducts_both_categories(self):
        sale = complete_sale(self.draft({self.shop.pk: 2, self.bar.pk: 2}).pk)
        self.shop.refresh_from_db()
        self.bar.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.subtotal, Decimal("25.20"))
        self.assertEqual(sale.discount, Decimal("0.00"))
        self.assertEqual(sale.total, Decimal("25.20"))
        self.assertEqual(self.shop.stock_quantity, 8)
        self.assertEqual(self.bar.stock_quantity, 0)
        self.assertEqual(sale.items.get(product=self.shop).unit_price, Decimal("12.50"))
        self.assertEqual(sale.items.get(product=self.bar).line_total, Decimal("0.20"))

    def test_insufficient_stock_leaves_all_lines_and_stock_unchanged(self):
        sale = self.draft({self.shop.pk: 1, self.bar.pk: 3})
        with self.assertRaises(InsufficientStock):
            complete_sale(sale.pk)
        self.shop.refresh_from_db()
        self.bar.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual((self.shop.stock_quantity, self.bar.stock_quantity), (10, 2))
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(sale.total, Decimal("0.00"))
        self.assertTrue(all(item.unit_price == Decimal("0.00") for item in sale.items.all()))

    def test_repeated_completion_does_not_deduct_or_reprice(self):
        sale = complete_sale(self.draft().pk)
        Product.objects.filter(pk=self.shop.pk).update(price=Decimal("99.00"), is_active=False)
        retried = complete_sale(sale.pk)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 8)
        self.assertEqual(retried.total, Decimal("25.00"))
        self.assertEqual(retried.items.get().unit_price, Decimal("12.50"))

    def test_price_is_taken_at_completion_then_stays_historical(self):
        sale = self.draft()
        Product.objects.filter(pk=self.shop.pk).update(price=Decimal("15.00"))
        complete_sale(sale.pk)
        Product.objects.filter(pk=self.shop.pk).update(price=Decimal("20.00"))
        sale.refresh_from_db()
        self.assertEqual(sale.total, Decimal("30.00"))
        self.assertEqual(sale.items.get().unit_price, Decimal("15.00"))

    def test_cancelling_draft_never_restores_undeducted_stock(self):
        sale = cancel_sale(self.draft().pk)
        cancel_sale(sale.pk)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.CANCELLED)

    def test_completed_cancellation_restores_once_and_preserves_snapshots(self):
        sale = complete_sale(self.draft().pk)
        Product.objects.filter(pk=self.shop.pk).update(is_active=False)
        cancel_sale(sale.pk)
        cancel_sale(sale.pk)
        self.shop.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.CANCELLED)
        self.assertEqual(sale.total, Decimal("25.00"))
        self.assertEqual(sale.items.get().line_total, Decimal("25.00"))

    def test_cancelled_sale_cannot_be_reopened(self):
        sale = cancel_sale(self.draft().pk)
        with self.assertRaises(ValidationError):
            complete_sale(sale.pk)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 10)

    def test_deactivated_product_rejected_at_completion(self):
        sale = self.draft()
        Product.objects.filter(pk=self.shop.pk).update(is_active=False)
        with self.assertRaises(ValidationError):
            complete_sale(sale.pk)
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.DRAFT)

    def test_zero_price_sale_still_deducts_quantity(self):
        Product.objects.filter(pk=self.shop.pk).update(price=Decimal("0.00"))
        sale = complete_sale(self.draft().pk)
        self.shop.refresh_from_db()
        self.assertEqual(sale.total, Decimal("0.00"))
        self.assertEqual(self.shop.stock_quantity, 8)

    def test_failure_after_deduction_rolls_back_database_writes(self):
        sale = self.draft()
        # Fault injection after real Product updates, not a replacement database.
        with patch("commerce.services.SaleItem.objects.bulk_update", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                complete_sale(sale.pk)
        self.shop.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(sale.items.get().unit_price, Decimal("0.00"))

    def test_empty_sale_cannot_complete(self):
        sale = Sale.objects.create(payment_method=Sale.PaymentMethod.CARD)
        with self.assertRaises(ValidationError):
            complete_sale(sale.pk)

    def test_missing_product_does_not_leave_partial_draft(self):
        missing_id = max(self.shop.pk, self.bar.pk) + 100
        with self.assertRaises(ValidationError):
            self.draft({self.shop.pk: 1, missing_id: 1})
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(SaleItem.objects.count(), 0)

    def test_duplicate_product_line_is_rejected_by_database(self):
        sale = self.draft()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SaleItem.objects.create(sale=sale, product=self.shop, quantity=1)

    def test_zero_quantity_is_rejected_by_database(self):
        sale = self.draft()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                sale.items.update(quantity=0)

    def test_inconsistent_sale_total_is_rejected_by_database(self):
        sale = self.draft()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Sale.objects.filter(pk=sale.pk).update(total=Decimal("1.00"))

    def test_sale_history_protects_product_and_sale_deletion(self):
        sale = complete_sale(self.draft().pk)
        for record in [self.shop, sale]:
            with self.subTest(model=type(record).__name__), self.assertRaises(ProtectedError):
                record.delete()

    def test_restock_overflow_rolls_back_cancellation(self):
        sale = complete_sale(self.draft().pk)
        Product.objects.filter(pk=self.shop.pk).update(stock_quantity=MAX_QUANTITY)
        with self.assertRaises(ValidationError):
            cancel_sale(sale.pk)
        sale.refresh_from_db()
        self.shop.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(self.shop.stock_quantity, MAX_QUANTITY)
