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


class Sale(models.Model):
    """Counter sale; an optional shared membership profile supplies benefits."""

    member = models.ForeignKey(
        "club.Member", null=True, blank=True, on_delete=models.PROTECT,
        related_name="commerce_sales",
    )

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        UPI = "UPI", "UPI"

    status = models.CharField(max_length=9, choices=Status.choices, default=Status.DRAFT)
    payment_method = models.CharField(max_length=4, choices=PaymentMethod.choices)
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "completed", "cancelled"]),
                name="commerce_sale_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(payment_method__in=["cash", "card", "UPI"]),
                name="commerce_sale_payment_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0, discount__gte=0, total__gte=0),
                name="commerce_sale_amounts_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(discount__lte=models.F("subtotal")),
                name="commerce_sale_discount_lte_subtotal",
            ),
            models.CheckConstraint(
                condition=models.Q(total=models.F("subtotal") - models.F("discount")),
                name="commerce_sale_total_matches",
            ),
        ]


class SaleItem(models.Model):
    # Protect transaction history; checkout/cancellation never deletes records.
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sale_items")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Zero values are placeholders in drafts; completion snapshots real prices.
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    line_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        ordering = ["product_id", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["sale", "product"], name="commerce_sale_item_product_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="commerce_sale_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0, discount__gte=0, line_total__gte=0),
                name="commerce_sale_item_amounts_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(discount__lte=models.F("unit_price") * models.F("quantity")),
                name="commerce_sale_item_discount_lte_value",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    line_total=models.F("unit_price") * models.F("quantity") - models.F("discount"),
                ),
                name="commerce_sale_item_total_matches",
            ),
        ]
