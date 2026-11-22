# Simulated payment checkout — 2026-11-22

This checkout demonstrates card/UPI success, failure and cancellation for
shop/bar sales and court bookings. It never charges money, collects card details
or sends UPI transfers. Receipts explicitly label successful payments as simulated
and show a `DEMO-<uuid>` reference.

## Run and demonstrate

Use the existing Django project and PostgreSQL 16 Docker environment. Set
`DEMO_PAYMENT_GATEWAY_ENABLED=True` for the demo. Without an explicit value it
follows Django DEBUG; outside DEBUG it defaults to disabled.

```text
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py migrate --plan
python -B manage.py migrate --noinput
python -B manage.py runserver 127.0.0.1:8000 --noreload
```

The existing local Docker database is `champions_club` at `127.0.0.1:5433`,
PostgreSQL 16.16. Its container and volume are unchanged. Do not use the legacy
`run_dev.ps1` PostgreSQL 17 startup path for this Docker environment.

- Shop/bar: open `/commerce/counter/`, select a real product, quantity and card
  or UPI, create a draft, then **Open demo checkout**. Failure/cancel leaves the
  draft and stock unchanged. Success completes the sale through `complete_sale`.
  Repeating success for the same Sale preserves its reference and deducts once.
  **Cancel sale** restores the original quantity once and retains snapshots.
- Courts: open `/club/bookings/new/` or `/club/availability/`, reserve a paid
  card/UPI slot, then choose a checkout outcome. A reservation is confirmed with
  payment pending until simulated success. Failure/cancel of the payment leaves
  the reservation confirmed and unpaid; **Cancel Booking & Free Slot** is the
  separate action that releases the court. Success retains the booking price
  snapshot and records payment paid plus simulation metadata. Cancelling the
  reservation retains any previous payment reference; no real refund occurs.
- Cash, free-plan entitlement and member-tab workflows retain existing behavior.
  Checkout links are hidden when disabled and manual electronic completion
  remains available. The user-requested anonymous demo access is unchanged.

## Interface and transaction behavior

| Named route | Method | Path |
| --- | --- | --- |
| `commerce:demo_payment` | GET/HEAD | `/commerce/demo-payment/<kind>/<pk>/` |
| `commerce:demo_payment_submit` | POST, CSRF | `/commerce/demo-payment/<kind>/<pk>/submit/` |

`kind` is `sale` or `booking`. POST fields are `csrfmiddlewaretoken`,
`checkout_token` and `outcome` (`success`, `failure`, `cancel`). Signed checkout
tokens expire after 600 seconds and bind target, amount, method and session nonce.
Browser amount/status/method overrides do not determine successful checkout.
Price, benefits, inventory and state are revalidated under PostgreSQL row locks.
No stock is reserved by GET or draft creation. Changed prices/benefits or depleted
stock require a reviewed checkout; failures roll back snapshots and deductions.

Success/cancel use named detail redirects. Failed attempts render retry feedback.
Invalid/expired token or outcome returns 400; stale price/state or stock conflict
409; missing target/disabled simulator 404; wrong method 405; missing CSRF 403;
database failure 503 with a generic message. Checkout responses are not cached.

New template: `frontend/templates/commerce/demo_payment.html`. Context keys:
`target_kind`, `target_id`, `target_label`, `payment_method`,
`payment_method_label`, `amount`, `checkout_token`, `payable`, `return_url`,
`error_message`, `payment_reference`, `payment_is_simulated`.

Sale completion and quoting share the existing Decimal line calculations and
Member/Plan eligibility policy. Lock order remains Sale → Member → Plan → items
→ products in ID order. Simulator completion wraps reference saving and existing
sale completion in one transaction. Booking checkout and cancellation serialize
on the same Booking row; cancellation rereads it after locking.

This is an optional demonstration flow, not verified payment processing. Existing
manual completion/booking interfaces remain supported. New draft requests are
not request-idempotent. Failure/cancel attempts are not persisted as a separate
ledger. No independent Payment model, provider callback, refund or login layer
has been added. Simulated completed sales still participate in existing dashboard
aggregates; they are demo data and never evidence of collected real revenue.

## Migrations and preservation

- `commerce.0004_sale_demo_payment_reference_and_more` depends on existing
  `commerce.0003_sale_member`.
- `club.0006_booking_demo_payment_reference_and_more` depends on existing
  `club.0005_booking_payment_method_booking_payment_status`.
- Each adds only `payment_is_simulated=False` and a blank
  `demo_payment_reference` (max length 40) to its existing record.

Both additive migrations were applied successfully to the verified local demo
database after testing. All 28 migrations are applied. A PostgreSQL custom-format
backup was saved outside Git at
`%TEMP%\champions-before-demo-gateway-20261122.dump` before application.
Checksums of every original column verified preservation of 21 products,
9 sales/items, 6 members, 3 plans, 5 courts and the existing booking/participant.
No existing transaction was relabelled as simulated.

Working branch: `feature/demo-payment-gateway`, based on main `920014b`, in
`.demo-payment-gateway-920014b`. All 140 files present at the continuation
checkpoint remain present. Original `feature/utkarsh-commerce` and its 26
untracked commerce files, older worktrees and Docker volume are preserved.
All UI work stays under `frontend/`; no old root templates/static are restored.

## Executed verification

Runtime: Django 5.2.19, Python 3.13.7, PostgreSQL 16.16. Tests migrated and removed
their disposable `test_champions_club` database. Verification used the existing
external Python environment documented in `POSTGRES_VERIFICATION.md`.

```text
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py test commerce.tests.test_demo_gateway --verbosity 1 --noinput
python -B manage.py test --verbosity 1 --noinput
git diff --check
```

- Gateway: 35 passed, including five concurrency tests (same-sale retries,
  competing sales, success/cancel race, same-booking retries and booking
  success/cancel race through the actual cancellation route).
- Full project: 282 passed, zero failures/errors/skips.
- Edge/Playwright: two browser audits passed for shop/bar and traditional/modal
  booking flows, payment failure/cancel/retry, receipts, CSRF and mobile layout.
  Shop total 25.00, bar total 2.40, booking total 250.00. Each sale stock 10→8→10.
  Mobile width 390px with no page overflow; no JavaScript or local asset errors.
- The first browser audit exposed an incorrect audit selector, then a real
  pre-existing mobile hero overflow. The selector was corrected externally;
  scoped responsive CSS and removal of unnecessary card placeholders fixed
  layout. Both final browser audits passed.

Browser audit script and screenshot/result artifacts remain external to the app
at `%TEMP%\champions-demo-payment-browser-audit.py` and the session's
visualizations `demo-payment-gateway` directory. No browser library is added to
application requirements.

Review the booking additions with Nayan, templates with Pratik, and migrations/
feature flag with Parth before merging. Only a feature-branch review PR is
intended; no direct main push or automatic merge.
