"""PostgreSQL transaction tests with independent connections and real row locks."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from commerce.models import Product, Sale
from commerce.services import cancel_sale, complete_sale, create_guest_sale


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL row locking")
class GuestSaleConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Last ball", category="shop", price=Decimal("1.00"), stock_quantity=1,
        )
        self.first = create_guest_sale(
            quantities={self.product.pk: 1}, payment_method=Sale.PaymentMethod.CASH,
        )
        self.second = create_guest_sale(
            quantities={self.product.pk: 1}, payment_method=Sale.PaymentMethod.UPI,
        )

    def run_parallel(self, calls):
        barrier = Barrier(len(calls))

        def worker(operation, sale_id):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '5s'")
                    cursor.execute("SET statement_timeout TO '10s'")
                barrier.wait(timeout=5)
                try:
                    return operation(sale_id).status
                except ValidationError as error:
                    return error.code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(worker, operation, sale_id) for operation, sale_id in calls]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_repeated_completion_deducts_once(self):
        results = self.run_parallel([(complete_sale, self.first.pk), (complete_sale, self.first.pk)])
        self.product.refresh_from_db()
        self.assertEqual(results, [Sale.Status.COMPLETED, Sale.Status.COMPLETED])
        self.assertEqual(self.product.stock_quantity, 0)

    def test_two_sales_compete_for_last_item_without_overselling(self):
        results = self.run_parallel([(complete_sale, self.first.pk), (complete_sale, self.second.pk)])
        self.product.refresh_from_db()
        self.assertCountEqual(results, [Sale.Status.COMPLETED, "insufficient_stock"])
        self.assertEqual(self.product.stock_quantity, 0)
        self.assertEqual(Sale.objects.filter(status=Sale.Status.COMPLETED).count(), 1)
        self.assertEqual(Sale.objects.filter(status=Sale.Status.DRAFT).count(), 1)

    def test_concurrent_cancellation_restores_once(self):
        complete_sale(self.first.pk)
        results = self.run_parallel([(cancel_sale, self.first.pk), (cancel_sale, self.first.pk)])
        self.product.refresh_from_db()
        self.assertEqual(results, [Sale.Status.CANCELLED, Sale.Status.CANCELLED])
        self.assertEqual(self.product.stock_quantity, 1)

    def test_completion_racing_cancellation_finishes_cancelled_with_stock_restored(self):
        results = self.run_parallel([(complete_sale, self.first.pk), (cancel_sale, self.first.pk)])
        self.product.refresh_from_db()
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, Sale.Status.CANCELLED)
        self.assertEqual(self.product.stock_quantity, 1)
        self.assertEqual(results[1], Sale.Status.CANCELLED)
        self.assertIn(results[0], [Sale.Status.COMPLETED, "invalid_sale_state"])
