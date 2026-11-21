"""Create missing demonstration catalogue records without resetting inventory."""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from commerce.models import Product


# Configurable illustrative demo catalogue, not official Champions Club prices.
DEMO_PRODUCTS = [
    {"name": "Tennis racket", "category": "shop", "price": Decimal("2499.00"), "stock_quantity": 12, "low_stock_threshold": 3},
    {"name": "Badminton racket", "category": "shop", "price": Decimal("1499.00"), "stock_quantity": 16, "low_stock_threshold": 4},
    {"name": "Tennis balls - pack of 3", "category": "shop", "price": Decimal("299.00"), "stock_quantity": 40, "low_stock_threshold": 10},
    {"name": "Badminton shuttlecocks - tube", "category": "shop", "price": Decimal("599.00"), "stock_quantity": 25, "low_stock_threshold": 6},
    {"name": "Court shoes", "category": "shop", "price": Decimal("1999.00"), "stock_quantity": 12, "low_stock_threshold": 3},
    {"name": "Club sports T-shirt", "category": "shop", "price": Decimal("499.00"), "stock_quantity": 30, "low_stock_threshold": 8},
    {"name": "Training shorts", "category": "shop", "price": Decimal("699.00"), "stock_quantity": 20, "low_stock_threshold": 5},
    {"name": "Racket grip", "category": "shop", "price": Decimal("149.00"), "stock_quantity": 35, "low_stock_threshold": 10},
    {"name": "Sports water bottle", "category": "shop", "price": Decimal("349.00"), "stock_quantity": 24, "low_stock_threshold": 6},
    {"name": "Sweatband set", "category": "shop", "price": Decimal("199.00"), "stock_quantity": 3, "low_stock_threshold": 5},
    {"name": "Mineral water", "category": "bar", "price": Decimal("20.00"), "stock_quantity": 100, "low_stock_threshold": 20},
    {"name": "Fresh lime soda", "category": "bar", "price": Decimal("60.00"), "stock_quantity": 40, "low_stock_threshold": 10},
    {"name": "Cold coffee", "category": "bar", "price": Decimal("99.00"), "stock_quantity": 30, "low_stock_threshold": 8},
    {"name": "Masala tea", "category": "bar", "price": Decimal("30.00"), "stock_quantity": 60, "low_stock_threshold": 12},
    {"name": "Grilled sandwich", "category": "bar", "price": Decimal("120.00"), "stock_quantity": 25, "low_stock_threshold": 6},
    {"name": "Veg burger", "category": "bar", "price": Decimal("110.00"), "stock_quantity": 20, "low_stock_threshold": 5},
    {"name": "French fries", "category": "bar", "price": Decimal("80.00"), "stock_quantity": 30, "low_stock_threshold": 8},
    {"name": "Sports energy drink", "category": "bar", "price": Decimal("90.00"), "stock_quantity": 6, "low_stock_threshold": 8},
]


class Command(BaseCommand):
    help = "Create missing illustrative shop/bar demo products; preserve existing stock and prices."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("The demo catalogue requires the shared PostgreSQL database.")
        self.stdout.write("Illustrative demonstration catalogue; existing records will be preserved.")
        created = 0
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [1128484866])
            pending = []
            for values in DEMO_PRODUCTS:
                matches = list(Product.objects.select_for_update().filter(name=values["name"]))
                if len(matches) > 1:
                    raise CommandError(f"Ambiguous product name: {values['name']}; no records changed.")
                if matches:
                    if matches[0].category != values["category"]:
                        raise CommandError(f"Category mismatch for {values['name']}; no records changed.")
                    continue
                product = Product(**values)
                product.full_clean()
                pending.append(product)
            for product in pending:
                product.save(force_insert=True)
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f"Created {created}; preserved {len(DEMO_PRODUCTS) - created}; total products {Product.objects.count()}."
        ))
