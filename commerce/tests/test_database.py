"""Run with Parth's actual PostgreSQL settings after the app is integrated."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from commerce.forms import ProductForm
from commerce.models import Product


class ProductDatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Tennis ball",
            category=Product.Category.SHOP,
            price=Decimal("12.50"),
            stock_quantity=10,
            low_stock_threshold=2,
        )

    def test_creation_round_trips_decimal_and_inventory(self):
        product = Product.objects.get(pk=self.product.pk)
        self.assertIsInstance(product.price, Decimal)
        self.assertEqual(product.price, Decimal("12.50"))
        self.assertEqual(product.stock_quantity, 10)
        self.assertEqual(product.low_stock_threshold, 2)
        self.assertTrue(product.is_active)
        product.full_clean()

    def test_database_rejects_invalid_category_even_without_model_validation(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.filter(pk=self.product.pk).update(category="food")
        self.product.refresh_from_db()
        self.assertEqual(self.product.category, Product.Category.SHOP)

    def test_database_rejects_negative_price_even_without_model_validation(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.filter(pk=self.product.pk).update(price=Decimal("-0.01"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal("12.50"))

    def test_database_rejects_negative_inventory_updates(self):
        for field in ["stock_quantity", "low_stock_threshold"]:
            with self.subTest(field=field):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        Product.objects.filter(pk=self.product.pk).update(**{field: -1})
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(self.product.low_stock_threshold, 2)

    def test_bulk_creation_cannot_bypass_inventory_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.bulk_create(
                    [
                        Product(
                            name="Invalid stock",
                            category=Product.Category.BAR,
                            price=Decimal("1.00"),
                            stock_quantity=-1,
                        )
                    ]
                )
        self.assertFalse(Product.objects.filter(name="Invalid stock").exists())

    def test_zero_price_and_inventory_can_be_persisted(self):
        product = Product.objects.create(
            name="Demo item",
            category=Product.Category.BAR,
            price=Decimal("0.00"),
        )
        product.full_clean()
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal("0.00"))
        self.assertTrue(product.is_low_stock)

    def test_valid_form_creates_bar_product(self):
        form = ProductForm(
            data={
                "name": "  Refreshment  ",
                "category": "bar",
                "price": "25.50",
                "stock_quantity": "8",
                "low_stock_threshold": "3",
                "is_active": "on",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        product.refresh_from_db()
        self.assertEqual(product.name, "Refreshment")
        self.assertEqual(product.category, Product.Category.BAR)
        self.assertEqual(product.price, Decimal("25.50"))
        self.assertEqual(product.stock_quantity, 8)

    def test_invalid_form_does_not_create_product(self):
        count = Product.objects.count()
        form = ProductForm(
            data={
                "name": "Invalid product",
                "category": "food",
                "price": "-0.01",
                "stock_quantity": "1.5",
                "low_stock_threshold": "-1",
            }
        )
        self.assertFalse(form.is_valid())
        for field in ["category", "price", "stock_quantity", "low_stock_threshold"]:
            self.assertIn(field, form.errors)
        self.assertEqual(Product.objects.count(), count)
