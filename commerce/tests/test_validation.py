"""Field validation tests that intentionally do not access a database."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from commerce.forms import ProductForm
from commerce.models import Product


class ProductValidationTests(SimpleTestCase):
    def make_product(self, **overrides):
        values = {
            "name": "Tennis ball",
            "category": Product.Category.SHOP,
            "price": Decimal("12.50"),
        }
        values.update(overrides)
        return Product(**values)

    def validate_fields(self, product):
        # Constraint validation queries the database. Those checks are exercised
        # separately in test_database.py against the shared database.
        product.full_clean(validate_unique=False, validate_constraints=False)

    def test_shop_and_bar_products_validate(self):
        for category in Product.Category.values:
            with self.subTest(category=category):
                self.validate_fields(self.make_product(category=category))

    def test_defaults_allow_new_products_without_stock(self):
        product = self.make_product()
        self.validate_fields(product)
        self.assertEqual(product.stock_quantity, 0)
        self.assertEqual(product.low_stock_threshold, 0)
        self.assertTrue(product.is_active)

    def test_zero_and_maximum_prices_validate(self):
        for price in [Decimal("0.00"), Decimal("99999999.99")]:
            with self.subTest(price=price):
                self.validate_fields(self.make_product(price=price))

    def test_invalid_prices_are_rejected(self):
        for price in [
            Decimal("-0.01"),
            Decimal("1.001"),
            Decimal("100000000.00"),
            Decimal("NaN"),
            Decimal("Infinity"),
        ]:
            with self.subTest(price=price):
                with self.assertRaises(ValidationError) as error:
                    self.validate_fields(self.make_product(price=price))
                self.assertIn("price", error.exception.message_dict)

    def test_missing_and_unknown_categories_are_rejected(self):
        for category in ["", "food", None]:
            with self.subTest(category=category):
                with self.assertRaises(ValidationError) as error:
                    self.validate_fields(self.make_product(category=category))
                self.assertIn("category", error.exception.message_dict)

    def test_invalid_names_are_rejected(self):
        for name in ["", " \t\n", "x" * 201, None]:
            with self.subTest(name=name):
                with self.assertRaises(ValidationError) as error:
                    self.validate_fields(self.make_product(name=name))
                self.assertIn("name", error.exception.message_dict)

    def test_negative_inventory_fields_are_rejected(self):
        for field in ["stock_quantity", "low_stock_threshold"]:
            with self.subTest(field=field):
                with self.assertRaises(ValidationError) as error:
                    self.validate_fields(self.make_product(**{field: -1}))
                self.assertIn(field, error.exception.message_dict)

    def test_threshold_can_exceed_stock(self):
        product = self.make_product(stock_quantity=1, low_stock_threshold=5)
        self.validate_fields(product)
        self.assertTrue(product.is_low_stock)

    def test_low_stock_includes_threshold_and_zero(self):
        for stock, threshold, expected in [(0, 0, True), (5, 5, True), (6, 5, False)]:
            with self.subTest(stock=stock, threshold=threshold):
                product = self.make_product(
                    stock_quantity=stock, low_stock_threshold=threshold
                )
                self.assertEqual(product.is_low_stock, expected)

    def test_inactive_products_remain_valid_inventory_records(self):
        self.validate_fields(self.make_product(is_active=False))

    def test_string_representation_uses_product_name(self):
        self.assertEqual(str(self.make_product()), "Tennis ball")

    def test_form_inventory_fields_reject_fractional_and_negative_input(self):
        form = ProductForm()
        for field in ["stock_quantity", "low_stock_threshold"]:
            for value in ["1.5", "-1", "NaN"]:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        form.fields[field].clean(value)

    def test_form_price_field_preserves_decimal_precision(self):
        field = ProductForm().fields["price"]
        self.assertEqual(field.clean("12.50"), Decimal("12.50"))
        # The model's minimum-price validator runs in ModelForm._post_clean;
        # this field-only test checks decimal parsing and precision.
        for value in ["12.501", "NaN"]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    field.clean(value)
