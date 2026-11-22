# Customer/member portal — 2026-11-22

Customer entry: `/customer/`. The existing staff dashboard remains `/`.
The user explicitly requested keeping anonymous staff demo access. Customer
pages require login for personal transactions and filter history by their owner,
but **the application as a whole is not private**: legacy staff ledgers, member
directories, exports and operational APIs remain open as requested. Do not claim
global privacy or production authorization from the portal checks.

## Features and accounts

Visitors can browse real active products, courts and membership plans. Court
availability uses the existing sixty-minute/half-hour `availability_grid` and
contains occupancy only, never booking/customer names. Past sessions cannot be
selected. Product/court links preselect only actual active records.

Customers register and log in through Django's existing User/session system.
Passwords use Django hashing and validators; logout is POST/CSRF. Registration
creates only a User and `frontend.CustomerAccount`; it does not create or claim
a Member, assign a plan, grant staff access or import existing staff transactions.
There is no separate application/database/auth provider.

`CustomerAccount.member` is an optional OneToOne link to Nayan's existing Member.
Staff verify identity and assign that link in Django admin at
`/admin/frontend/customeraccount/`. Do not link accounts merely because an
email/name matches and do not accept a submitted Member ID from signup. Existing
Member/Plan fields and benefit policies are unchanged. Linked customers receive
benefits from the existing services; unlinked customers purchase/book as guests.
Membership enrollment/payment is not implemented: plan pages are informational
and direct customers to the club to enroll or link their existing membership.

## Routes and interface

| Named route | Method | Path |
| --- | --- | --- |
| `customer:home` | GET/HEAD | `/customer/` |
| `customer:shop` | GET/HEAD | `/customer/shop/` |
| `customer:courts` | GET/HEAD | `/customer/courts/` |
| `customer:plans` | GET/HEAD | `/customer/plans/` |
| `customer:register` | GET/POST, CSRF | `/customer/register/` |
| `customer:login` | GET/POST, CSRF | `/customer/login/` |
| `customer:logout` | POST, CSRF | `/customer/logout/` |
| `customer:dashboard` | GET/HEAD, login | `/customer/account/` |
| `customer:booking_create` | GET/POST, login/CSRF | `/customer/bookings/new/` |
| `customer:booking_detail` | GET/HEAD, owner | `/customer/bookings/<pk>/` |
| `customer:booking_cancel` | POST, owner/CSRF | `/customer/bookings/<pk>/cancel/` |
| `customer:sale_create` | POST, login/CSRF | `/customer/sales/create/` |
| `customer:sale_detail` | GET/HEAD, owner | `/customer/sales/<pk>/` |
| `customer:sale_cancel` | POST, owner/CSRF | `/customer/sales/<pk>/cancel/` |
| `customer:checkout` | GET/HEAD, owner | `/customer/checkout/<kind>/<pk>/` |

Signup: `username`, `first_name`, `email`, `password1`, `password2`.
Login: `username`, `password`, optional safe same-host `next`.
Purchase: `product`, `quantity`, `payment_method` (`card`, `UPI`).
Booking: `court`, `date`, `start_time` (`HH:MM`), `payment_method` (`card`, `upi`).
Book future sessions within 90 days, using club-local time Asia/Kolkata. Booking
types are standard for this first portal milestone. No caller price, Member,
owner, discount, stock, payment status or plan is accepted from customer forms.

`frontend.customer_services` delegates Sale creation to `create_sale`, and
Booking creation to its existing validated/snapshotted save. Ownership comes
only from the authenticated User and is stored on nullable `Sale.customer` and
`Booking.customer`. Null ownership preserves existing staff/guest records.
The portal retains shared overlap constraints, member daily limits, Decimal
pricing, discounts and atomic inventory completion.

Customers can cancel unpaid purchase drafts and unpaid/waived reservations
idempotently. Completed purchases and paid bookings require club assistance;
the portal cannot imply a real refund through stock/slot cancellation. The
middleware also prevents customers bypassing this policy through legacy
cancel/complete/roster mutation URLs. Staff retain existing operational access.

Checkout reuses existing local simulator or configured Razorpay Test Mode,
including server-priced orders/signatures/capture checks. It renders customer
navigation and returns to the owner's customer detail page. Neither keys nor
money logic appear in portal templates. Provider failure/cancel semantics remain
as documented in `commerce/RAZORPAY_TEST_MODE.md`.

Authenticated cross-account IDs return404; anonymous portal actions redirect to
login. Customer-owned records accessed through legacy detail/receipt/payment
URLs also reject anonymous/other accounts. These record checks coexist with
the user's requested anonymous staff directory/reporting access and do not
turn those aggregate screens into private pages.

## Frontend and team handoff

All new presentation is in `frontend/templates/customer/` with scoped
`frontend/static/css/customer.css`, using the shared style tokens and assets.
Existing staff templates/colors/navigation were preserved. Customer navigation
contains only courts, shop, plans, account and login/signup. There is no staff
Member picker or transaction selector in the customer screens.

Context: home `courts/products/plans`; shop `products/form`; courts
`selected_date/today/selected_court/operating_hours/court_grid`; plans `plans`;
auth `form/next`; booking form `form/member`; account `account/member/bookings/sales`;
detail `booking` or `sale/sale_items`. Shared payment context matches its original
template contract, with customer-owned return links. All HTML forms use CSRF.

Pratik reviews the separate customer presentation; Nayan reviews the additive
booking owner field and existing-member account link; Parth reviews migration
order and access middleware. No existing Member model or competing Django
project, framework, staff account or credential was created.

## Migrations, data and verification

Additive migrations:

- `club.0008_booking_customer`, dependent on existing `club.0007` + auth User.
- `commerce.0006_sale_customer`, dependent on existing `commerce.0005` + auth User.
- `frontend.0001_initial`, creates CustomerAccount with actual Member/User links.

Applied to local PostgreSQL16.16 after backup outside Git at
`%TEMP%\champions-before-customer-portal-20261122.dump`. All33 migrations applied.
Original-column checksums preserved existing 21 products, 18 sales/items,
7 members, 3 plans, 5 courts, 7 bookings, 5 participants and the one existing User.
These counts reflect the live development database immediately before applying
the migration. No customer demo records or fake membership links were seeded.
Original `feature/utkarsh-commerce` work, local `.env` and Docker volume preserved.

Executed with Django5.2.19/Python3.13.7/PostgreSQL16.16:

```text
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py test frontend.tests.test_customer --verbosity 1 --noinput
python -B manage.py test --verbosity 1 --noinput
git diff --check
```

Tests use runtime `RAZORPAY_TEST_MODE_ENABLED=False` as baseline, with appropriate
test overrides, so they do not use configured private keys or provider network.
The ignored local `.env` still enables Razorpay for interactive use.

- Customer tests: **32 passed**, including signup/identity spoofing, password
  hashing, safe login redirects, access, CSRF, book limits/conflicts, member
  pricing, product/date validation, snapshots, cancellation and payment returns.
- Full project: **346 run, 343 passed, 3 failed**, zero errors/skips. All three
  failures existed on main4fe8511 before portal work: legacy booking GET now
  redirects instead of rendering, dashboard label `Court Booking Value` removed,
  and inventory link changed from admin edit to POS. Do not report all tests pass.
- Edge browser audit: **1 passed**, signup → account → purchase → local simulated
  checkout → account detail, stock10→8, completed customer cancellation blocked,
  staff cancellation restored10; court booking/overlap/unpaid cancellation,
  logout/login, anonymous/cross-account access and mobile390px. No JavaScript
  or local asset errors. Actual Razorpay was not used in this audit.

External audit: `%TEMP%\champions-customer-browser-audit.py`, screenshots/results
in the session's `customer-portal` visualization directory. Disposable test DBs
were removed. System/migration/whitespace checks passed.

Work is isolated on `feature/customer-portal` based on main4fe8511. The unrelated
missing `razorpay==2.0.1` dependency restoration from the previous pull remains
included because shared provider views require that import. Staff frontend test
failures and unrelated anonymous staff privacy policy remain separate issues.
