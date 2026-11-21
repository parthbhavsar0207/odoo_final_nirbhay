"""Repeatable demonstration catalog seeding on actual PostgreSQL."""

from decimal import Decimal
from io import StringIO
from unittest import skipUnless

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from commerce.management.commands.seed_commerce_data import DEMO_PRODUCTS
from commerce.models import Product, Sale, SaleItem
from commerce.services import cancel_sale, complete_sale, create_guest_sale


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL demo seeding")
class DemoCatalogTests(TestCase):
    def seed(self):
        output = StringIO()
        call_command("seed_commerce_data", stdout=output)
        return output.getvalue()

    def test_creates_full_shop_and_bar_catalog_with_valid_decimal_inventory(self):
        self.seed()
        self.assertEqual(Product.objects.count(), 18)
        self.assertEqual(Product.objects.filter(category=Product.Category.SHOP).count(), 10)
        self.assertEqual(Product.objects.filter(category=Product.Category.BAR).count(), 8)
        for product in Product.objects.all():
            with self.subTest(product=product.name):
                product.full_clean()
                self.assertIsInstance(product.price, Decimal)
                self.assertGreaterEqual(product.price, Decimal("0.00"))
                self.assertGreaterEqual(product.stock_quantity, 0)
                self.assertTrue(product.is_active)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(SaleItem.objects.count(), 0)

    def test_reseed_preserves_ids_live_stock_prices_and_completed_sale_history(self):
        self.seed()
        ids_before = dict(Product.objects.values_list("name", "pk"))
        product = Product.objects.filter(stock_quantity__gte=2, price__gt=0).first()
        initial_stock = product.stock_quantity
        sale = complete_sale(create_guest_sale(
            quantities={product.pk: 2}, payment_method=Sale.PaymentMethod.CASH,
        ).pk)
        saved_total = sale.total
        saved_item = tuple(sale.items.values_list("unit_price", "discount", "line_total").get())
        edited_price = product.price + Decimal("1.00")
        Product.objects.filter(pk=product.pk).update(price=edited_price)

        self.seed()

        self.assertEqual(dict(Product.objects.values_list("name", "pk")), ids_before)
        product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(product.stock_quantity, initial_stock - 2)
        self.assertEqual(product.price, edited_price)
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.total, saved_total)
        self.assertEqual(tuple(sale.items.values_list("unit_price", "discount", "line_total").get()), saved_item)
        cancel_sale(sale.pk)
        cancel_sale(sale.pk)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, initial_stock)

    def test_existing_demo_product_values_are_preserved_even_when_inactive(self):
        definition = DEMO_PRODUCTS[0]
        product = Product.objects.create(
            name=definition["name"], category=definition["category"],
            price=Decimal("77.70"), stock_quantity=1, low_stock_threshold=17,
            is_active=False,
        )
        original = Product.objects.filter(pk=product.pk).values().get()

        self.seed()
        self.seed()

        self.assertEqual(Product.objects.count(), 18)
        self.assertEqual(Product.objects.filter(pk=product.pk).values().get(), original)

    def test_duplicate_reserved_name_aborts_without_creating_partial_catalog(self):
        definition = DEMO_PRODUCTS[-1]
        for _ in range(2):
            Product.objects.create(
                name=definition["name"], category=definition["category"],
                price=Decimal("3.00"), stock_quantity=4,
            )
        originals = list(Product.objects.values().order_by("pk"))

        with self.assertRaises(CommandError):
            self.seed()

        self.assertEqual(list(Product.objects.values().order_by("pk")), originals)
        self.assertEqual(Sale.objects.count(), 0)

    def test_category_mismatch_aborts_without_creating_partial_catalog(self):
        definition = DEMO_PRODUCTS[-1]
        wrong_category = "shop" if definition["category"] == "bar" else "bar"
        product = Product.objects.create(
            name=definition["name"], category=wrong_category,
            price=Decimal("3.00"), stock_quantity=4,
        )
        original = Product.objects.filter(pk=product.pk).values().get()

        with self.assertRaises(CommandError):
            self.seed()

        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Product.objects.filter(pk=product.pk).values().get(), original)

    def test_seeding_preserves_unrelated_products_and_drafts(self):
        product = Product.objects.create(
            name="Existing custom inventory", category="shop", price=Decimal("9.25"),
            stock_quantity=3, low_stock_threshold=2,
        )
        sale = create_guest_sale(quantities={product.pk: 2}, payment_method="card")
        original_product = Product.objects.filter(pk=product.pk).values().get()
        original_sale = Sale.objects.filter(pk=sale.pk).values().get()
        original_items = list(sale.items.values())

        self.seed()
        self.seed()

        self.assertEqual(Product.objects.count(), 19)
        self.assertEqual(Product.objects.filter(pk=product.pk).values().get(), original_product)
        self.assertEqual(Sale.objects.filter(pk=sale.pk).values().get(), original_sale)
        self.assertEqual(list(sale.items.values()), original_items)
