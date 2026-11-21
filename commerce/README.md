# Commerce Product milestone — Utkarsh

> Current delivery: Product, guest/member sales, inventory and shared frontend
> are published as dependent PRs. Read [DELIVERY.md](DELIVERY.md) and
> [MEMBER_SALES.md](MEMBER_SALES.md). Preparation notes below are historical.

> Guest-sales update: Sale, SaleItem, Decimal guest calculations and PostgreSQL
> transaction services are now prepared. See [GUEST_SALES.md](GUEST_SALES.md) for
> the current interface, migration, tests and integration limits. The Product-only
> preparation notes below describe the earlier baseline; Product code, admin,
> form, initial migration and original tests have been retained.

## Current integration status

This package is an independent Django app, not a project shell. The shared
`INTEGRATION_CONTRACT.md` remains authoritative. At preparation time the fetched
repository had only the integration contract and README on `main`; no local or
remote teammate foundation branch was available. Existing tracked files are
unchanged. Work is on `feature/utkarsh-commerce`.

Prepared here: Product, ProductForm, ProductAdmin, an independent initial
migration, field-validation tests and database tests. There are no shared
settings, database credentials, Compose files, frontend templates, member
models, Sale models or live catalog routes in this slice.

The app package can be moved into Parth's agreed Python package layout before
integration. If its import path changes, update `CommerceConfig.name`, test
imports and the shared app registration together. Do not scaffold another
project to run this package.

## Exact Product design

| Field | Django definition | Rules |
| --- | --- | --- |
| `id` | App-local `BigAutoField` | Automatic primary key. |
| `name` | `CharField(max_length=200)` | Required; whitespace-only names rejected by a model validator. ProductForm strips surrounding whitespace. Names need not be unique. |
| `category` | `CharField(max_length=4, choices=Category.choices)` | Required; only `shop` or `bar`; checked by validation and a database constraint. |
| `price` | `DecimalField(max_digits=10, decimal_places=2)` | Required; Decimal, from `0.00` through `99999999.99`. Extra decimal places rejected by model/form validation. Zero allowed; no invented minimum business price. Database CHECK rejects negative values. |
| `stock_quantity` | `PositiveIntegerField(default=0)` | Whole units, nonnegative, maximum 2147483647. No fractional quantities in submitted forms. Database CHECK rejects negatives. |
| `low_stock_threshold` | `PositiveIntegerField(default=0)` | Same integer bounds as stock. May exceed current stock. Database CHECK rejects negatives. |
| `is_active` | `BooleanField(default=True)` | Retains inactive products as inventory records. Future counter-sale services must reject inactive products. |

`is_low_stock` is a computed property: `stock_quantity <= low_stock_threshold`.
It includes out-of-stock products and does not store a second inventory total.
Default ordering is category, name, then primary key.

Ordinary Django ORM `save()`, `create()`, `update()` and `bulk_create()` do not
automatically run model validation. ProductForm/admin validate submitted data;
future trusted import/service paths must call `full_clean()` before saving.
Database constraints enforce category and nonnegative money/inventory even
when model validation is bypassed. Field precision validation rejects excess
decimal places before storage; PostgreSQL NUMERIC alone may round them.

The four explicitly named CHECK constraints are:

- `commerce_product_category_valid`
- `commerce_product_price_gte_0`
- `commerce_product_stock_gte_0`
- `commerce_product_threshold_gte_0`

The Product migration has `dependencies = []`: Product needs no shared core
tables. A later member-linked Sale migration must depend on Nayan's actual
core migration and the preceding commerce migration. Never add a guessed
dependency to a nonexistent model or migration.

## Admin and form contract

ProductAdmin uses ProductForm. Its list displays ID, name, category, price,
stock quantity, threshold, a boolean low-stock indicator and active status.
Filters are category and active status; name is searchable. The low-stock
indicator is read-only. There is no inline inventory list editing.

ProductForm accepts exactly:
`name`, `category`, `price`, `stock_quantity`, `low_stock_threshold`, `is_active`.
Model and form validation determine valid input. Do not trust submitted prices
or stock values from a future sale form; sale services must reread locked
Product records.

## Verification and tests

Preparation used an isolated temporary environment outside the repository:
Python 3.13.7 and Django 5.2.19. This does not select or change the shared
project's Django version or dependency files. The current constraint syntax
requires Django 5.1 or newer; confirm compatibility with Parth's chosen version
before integration. Constraints follow the
[official Django constraint API](https://docs.djangoproject.com/en/5.2/ref/models/constraints/).

Executed before shared foundation: 13 database-free validation tests, Product
model checks, ProductAdmin checks, and migration-state consistency checking.
These use a temporary in-process Django bootstrap with the dummy database
backend; they do not verify PostgreSQL, table creation or the shared project.
No SQLite replacement database is used. An initial field-only test incorrectly
expected a model validator to run; its scope was corrected before the final run.

`test_validation.py` covers shop/bar categories, required and whitespace names,
name length, defaults, zero/maximum/negative/overprecision/nonfinite prices,
negative inventory, low-stock boundaries, inactive records and form field input.
Its `full_clean()` calls deliberately disable constraint queries; actual database
constraints are covered separately.

`test_database.py` contains 8 PostgreSQL-compatible database tests: Product
round-trip creation and full validation; category, price and inventory CHECKs
through direct ORM updates; invalid bulk creation rollback; zero-price and
zero-stock persistence; valid complete form submission; and invalid form input.
Nested `transaction.atomic()` blocks isolate expected IntegrityError failures.
These database tests have NOT been executed: no shared Django/PostgreSQL setup,
Docker CLI or psql is available in the current workspace. The Product migration
has been generated, not applied to PostgreSQL.

Once Parth's foundation is present and this app is registered, use the actual
documented project/container invocation for these Django commands:

```text
python manage.py check
python manage.py makemigrations commerce --check --dry-run
python manage.py migrate
python manage.py test commerce.tests.test_validation
python manage.py test commerce.tests.test_database
```

Use the real PostgreSQL 16 test environment and an account allowed to create
the test database. Do not claim an isolated validation run verifies database
constraints, migrations, concurrency or the end-to-end catalog.

To reproduce only the pre-foundation validation/checks, install Django 5.2 in
an isolated environment outside the repository and run the following from the
repository root with that environment's Python. This bootstrap configures only
the current process; it is not a project settings file or application server:

```python
import sys
import unittest

import django
from django.conf import settings

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.auth", "django.contrib.contenttypes",
        "django.contrib.sessions", "django.contrib.messages",
        "django.contrib.admin", "commerce.apps.CommerceConfig",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.dummy"}},
    SECRET_KEY="temporary-commerce-verification-only",
    USE_TZ=True,
    TIME_ZONE="Asia/Kolkata",
)
django.setup()

from django.contrib import admin
from django.core.checks import Tags, run_checks
from django.core.management import call_command
from commerce.models import Product

errors = run_checks(tags=[Tags.models]) + admin.site._registry[Product].check()
for error in errors:
    print(error)
if errors:
    raise SystemExit(1)
call_command("makemigrations", "commerce", check=True, dry_run=True)
suite = unittest.TestSuite(
    unittest.defaultTestLoader.loadTestsFromName(label)
    for label in ["commerce.tests.test_validation", "commerce.tests.test_sales_rules"]
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
```

## Required handoffs before integration

Parth provides/coordinates:

1. The exact shared foundation branch/commit and app package layout. Confirm
   how `commerce.apps.CommerceConfig` is registered in `INSTALLED_APPS`.
2. The shared Django version/dependencies, manage.py, PostgreSQL 16 Compose
   service, safe environment example and actual startup/test commands. Shared
   settings use `Asia/Kolkata`; secrets stay outside version control.
3. A working PostgreSQL migration/test run and test-database permissions. Confirm
   the independent Product migration fits the shared migration graph; coordinate
   the later core dependency for member-linked Sale.
4. The shared base template path/blocks, URL mount and existing staff access
   conventions so commerce routes integrate without replacing shared files.

Nayan provides before member-linked sales:

1. The import/app label, primary key type and exact applied migration creating
   Member and MembershipPlan. Provide the actual Member-to-plan field name.
2. Exact shop/bar discount field names, Decimal precision, units (percent or
   fraction), valid range and configurable demo values for Gold/Silver/Junior.
3. Membership start/end semantics, plan active flag and any suspended flag;
   agree discount eligibility for expired/suspended/inactive memberships and
   the shared club-local date policy. Do not guess these rules or percentages.
4. A member/plan fixture for each tier suitable for integration tests. Coordinate
   the Member foreign-key deletion policy to preserve sale history.

## Handoff to Pratik and next milestones

The form field names above are ready for coordination. No frontend templates
or routes exist yet. Proposed route namespace/names, subject to Parth's mount:
`commerce:product_list`, `commerce:product_create`, `commerce:product_update`.
Proposed template paths: `commerce/product_list.html` (`products`) and
`commerce/product_form.html` (`form`, plus `product` for editing). Utkarsh owns
views/forms and will finalize this contract before Pratik connects templates;
Pratik owns the actual markup, HTMX/Alpine and styling. Staff access conventions
and shared base template blocks must be known before wiring live views.

After Product integration passes PostgreSQL tests, add Sale/SaleItem against
Nayan's shared Member and plan. Keep transaction logic in explicit services:
Decimal discounts read from the actual plan, completion-time price/discount
snapshots, sale-row locks and consistently ordered product-row locks inside
`transaction.atomic()`, stock revalidation and all-or-nothing deduction.
Repeated completion of the same completed Sale must return without further
stock changes. Coordinate request idempotency for creation of duplicate drafts.
Cancellation of drafts changes no stock; cancellation of completed sales restores
stock exactly once under the same locking discipline. Finalize payment values
(`cash`, `card`, `UPI`), eligibility and rounding before those migrations/services.
Reporting reads completed Sale/SaleItem records; confirmed booking value stays
separate. No Payment, Member or MembershipPlan model is created here.
