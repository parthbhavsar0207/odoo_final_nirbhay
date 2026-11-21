from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models


class Product(models.Model):
    class Category(models.TextChoices):
        SHOP = "shop", "Shop"
        BAR = "bar", "Bar / cafeteria"

    name = models.CharField(
        max_length=200,
        validators=[
            RegexValidator(r"\S", "Enter a name containing a non-whitespace character.")
        ],
    )
    category = models.CharField(max_length=4, choices=Category.choices)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    stock_quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "name", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(category__in=["shop", "bar"]),
                name="commerce_product_category_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="commerce_product_price_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(stock_quantity__gte=0),
                name="commerce_product_stock_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(low_stock_threshold__gte=0),
                name="commerce_product_threshold_gte_0",
            ),
        ]

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold

    def __str__(self):
        return self.name
