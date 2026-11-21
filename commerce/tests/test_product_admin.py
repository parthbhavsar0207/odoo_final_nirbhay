"""Product admin regression tests against real commerce inventory changes."""

from decimal import Decimal
from unittest import skipUnless

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase

from commerce.models import Product, Sale
from commerce.services import complete_sale, create_guest_sale


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL sale completion")
class ProductAdminInventoryTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Tennis ball", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )
        self.request = RequestFactory().get("/admin/commerce/product/")
        self.request.user = get_user_model()(is_staff=True, is_superuser=True)
        self.product_admin = admin.site._registry[Product]

    def test_existing_product_admin_form_cannot_set_absolute_stock(self):
        form_class = self.product_admin.get_form(self.request, self.product)
        self.assertNotIn("stock_quantity", form_class.base_fields)
        self.assertIn("stock_quantity", self.product_admin.get_readonly_fields(self.request, self.product))

    def test_new_product_admin_can_set_initial_stock(self):
        form_class = self.product_admin.get_form(self.request)
        self.assertIn("stock_quantity", form_class.base_fields)
        form = form_class(data={
            "name": "Refreshment", "category": "bar", "price": "1.00",
            "stock_quantity": "5", "low_stock_threshold": "2", "is_active": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save(commit=False)
        self.product_admin.save_model(self.request, product, form, change=False)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 5)

    def test_stale_admin_price_edit_preserves_completed_sale_deduction(self):
        stale_product = Product.objects.get(pk=self.product.pk)
        form_class = self.product_admin.get_form(self.request, stale_product)
        form = form_class(data={
            "name": stale_product.name, "category": stale_product.category,
            "price": "15.00", "stock_quantity": "10",
            "low_stock_threshold": "2", "is_active": "on",
        }, instance=stale_product)
        self.assertTrue(form.is_valid(), form.errors)
        stale_product = form.save(commit=False)
        sale = create_guest_sale(
            quantities={self.product.pk: 2}, payment_method=Sale.PaymentMethod.CASH,
        )
        complete_sale(sale.pk)
        self.product_admin.save_model(self.request, stale_product, form, change=True)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)
        self.assertEqual(self.product.price, Decimal("15.00"))
        self.assertEqual(sale.items.get().unit_price, Decimal("12.50"))
