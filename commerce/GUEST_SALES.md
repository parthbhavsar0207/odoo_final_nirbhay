# Guest sales — independent commerce milestone

## Scope and integration status

This is Utkarsh's commerce backend on `feature/utkarsh-commerce`. It extends the
existing Product app; Product's definition, admin, form, initial migration and
tests are retained. All 11 original files remain. No teammate-owned files,
shared settings, Docker configuration or templates have been changed.

The guest-only milestone is authorized while waiting for Nayan. There is no
Member, MembershipPlan, substitute customer model, placeholder member ID or
independent Payment model. Every sale currently represents a guest and has zero
discount. Do not use this interface for member-discount sales yet.

Parth's foundation is still absent from the checkout and fetched origin branches.
The code is prepared and its database-free rules are tested; it is not yet a
running or PostgreSQL-verified integration. A later member FK migration must
use Nayan's actual app label and migration dependency.

## Records and migration

`Sale` has an automatic ID, `status` (`draft`, `completed`, `cancelled`),
`payment_method` (`cash`, `card`, `UPI`), `subtotal`, `discount`, `total` and
`created_at`. Totals are DecimalField(14, 2), initially zero. Status/payment
choices, nonnegative totals, discount <= subtotal and total = subtotal - discount
have database CHECKs. Recording the payment method does not process a payment.

`SaleItem` has protected sale/product foreign keys, positive integer `quantity`,
DecimalField(10, 2) `unit_price`, DecimalField(14, 2) `discount` and `line_total`.
Draft price/amount fields are zero placeholders; completion supplies snapshots.
Database constraints require positive quantity, nonnegative amounts, discount <=
unit_price * quantity, and line_total = unit_price * quantity - discount. A unique
constraint permits only one line per product per sale. Referenced Products and
Sales cannot be hard-deleted while items exist.

`0002_guest_sales.py` depends only on `commerce.0001_initial`. It creates these
guest records without an external dependency. The existing Product migration is
unchanged. Neither migration has been applied to PostgreSQL here.

The amount ceiling is 999999999999.99 per line/sale; the calculation layer
rejects overflow before deductions. Quantities must be actual positive Python
integers through 2147483647; floats, booleans and fractional quantities are
rejected by the service input rules. Product prices must be finite nonnegative
Decimal values within Product's existing precision. Guest arithmetic needs no
discount rounding policy; it uses exact cent amounts and zero discount.

## Service interface

```python
from commerce.models import Sale
from commerce.services import create_guest_sale, complete_sale, cancel_sale

# product_id is the ID of an existing active Product.
sale = create_guest_sale(
    quantities={product_id: 2},
    payment_method=Sale.PaymentMethod.UPI,
)
completed_sale = complete_sale(sale.pk)
same_completed_sale = complete_sale(sale.pk)  # no second deduction/repricing
cancelled_sale = cancel_sale(sale.pk)
same_cancelled_sale = cancel_sale(sale.pk)    # no second restoration
```

- `create_guest_sale` accepts product-ID -> quantity mapping plus a payment
  method. It checks inputs and active products, creates draft/items atomically,
  and neither reserves stock nor accepts caller-supplied amounts or discounts.
- `complete_sale` locks Sale, its items and Products inside `transaction.atomic()`.
  Products are locked in ascending primary-key order. Every item's stock, active
  flag and price, plus the entire total, are validated before any deduction.
  Conditional `F()` updates deduct stock; item snapshots, sale totals and completed
  status are saved within the same transaction. Prices come from current locked
  Product rows at completion, not the draft or browser.
- A retry of a completed Sale returns immediately after the sale-row lock,
  preserving stock and historical amounts even if products change later. A
  cancelled Sale cannot complete. Idempotency currently covers retries against
  the same Sale ID; two separate calls to create_guest_sale create separate
  drafts. A future HTTP checkout must coordinate draft/request idempotency.
- `cancel_sale` locks Sale first. Cancelling a draft changes status without stock
  changes. Cancelling a completed Sale locks its items/products in the same order,
  validates restoration bounds, restores quantities and marks it cancelled in one
  transaction. Already-cancelled Sales return without touching stock. Inactive
  products can be restocked. Restock overflow aborts cancellation without changing
  the completed Sale or any stock.
- Cancelled records retain original monetary snapshots for audit. Reporting must
  filter completed status; confirmed booking value remains separate. Historical
  category reporting needs an agreed category-change/snapshot policy before the
  reporting milestone; do not claim this code implements that policy.

These services require the configured default PostgreSQL connection with row
locking support and fail with `NotSupportedError` on other backends. Missing Sale
IDs raise `Sale.DoesNotExist`; invalid input/state raises `ValidationError`;
insufficient stock raises its `InsufficientStock` subclass with code
`insufficient_stock`. Database failures propagate outside the atomic block so
rollback is not swallowed. Do not retry unexpected database errors blindly.

All checkout and cancellation writes must use these services. No Sale admin,
item-edit endpoints or model-save side effects are added. Future draft-edit
services must lock the parent Sale and reject terminal statuses before mutating
items/payment details. Direct ORM/admin/SQL writes are not a supported checkout
interface; concurrent manual stock overwrites bypass service guarantees.

The transaction design follows Django's official documentation on
[atomic transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
and [row locking](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update).
Database concurrency behavior still needs the real PostgreSQL run below.

## Tests and actual verification

The temporary Python 3.13.7 / Django 5.2.19 environment outside this repository
was reused. No shared dependencies or framework version were changed.

Executed: **45 database-free tests passed** (13 existing Product tests plus 32
guest calculations, inventory rules, lifecycle decisions and model-field tests).
The isolated bootstrap in commerce/README.md now includes both modules. It uses
the dummy database backend, never SQLite. Pure state-decision tests check retry
and cancellation rules; they do not execute real transactional inventory changes.

PostgreSQL tests prepared but **not executed**:

- 8 original Product database tests.
- 18 guest-sale database tests for draft behavior, mixed-category completion,
  stock insufficiency, historical prices, retry/cancellation idempotency, zero
  prices, invalid products, constraints, protected history and restock overflow.
  The rollback test injects an exception after actual Product writes to verify
  those writes roll back when the later snapshot write fails.
- 4 `TransactionTestCase` concurrency tests using real independent connections:
  repeated completion, two sales competing for the last item, concurrent
  cancellation and completion racing cancellation. Session-local lock/statement
  timeouts prevent these tests from hanging indefinitely. Guest database and
  concurrency test classes explicitly skip non-PostgreSQL backends.

After Parth supplies the foundation and app registration, use the actual shared
environment/container invocation for:

```text
python manage.py check
python manage.py makemigrations commerce --check --dry-run
python manage.py showmigrations commerce --plan
python manage.py migrate commerce
python manage.py test commerce.tests
```

Confirm PostgreSQL **16** and the safe development/test database first. The
account needs test-database permissions. Do not reset shared data. Do not count
skipped/non-PostgreSQL tests or an offline migration check as PostgreSQL success.

## Team handoff and next step

Parth: supply the real project branch, Django version/layout, app registration,
PostgreSQL 16 settings/Compose and documented startup/migration/test commands.
Confirm Product/guest migration integration without rewriting teammates' work.

Nayan: supply the actual Member/Plan models and migration names, relation field,
shop/bar discount names and units, eligibility semantics for expired/suspended
members and inactive plans, and agreed demo values. Only then add the optional
shared Member FK and member-discount services/tests. No guessed percentages,
fixed discounts or official prices are present here.

Pratik: the Python service signatures above are ready for coordination; no live
sale routes, submitted field contract or frontend templates are implemented yet.
Views must parse quantities/payment, invoke services with Sale IDs and display
validation errors. They must not calculate prices/discounts or deduct stock.
Finalize named routes, context, permissions and duplicate-request behavior with
Utkarsh after the shared layout and staff-access conventions are available.

Highest-priority integration task: run all migrations and database/concurrency
tests in Parth's actual PostgreSQL 16 environment, fixing only commerce defects.
