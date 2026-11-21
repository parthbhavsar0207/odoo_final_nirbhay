# Merged-main verification and booking fixes - 2026-11-22

Fetched GitHub main at `112614093ee1774724bc38cccd1891cb6e86e4fb`, containing
merged PRs #12 and #13. Its tree exactly matches the previously tested
completion commit `c9d94d0`. The original completion checkout remains clean.

## Verification of published main

- Full PostgreSQL suite: 226 passed, zero failures/errors/skips.
- System checks and migration consistency passed; no migrations pending.
- 58 read-only live routes/assets returned 200: dashboard, members, plans,
  bookings, all ten activity pages, guest/member counter, existing sale details,
  search, FAQ and CSS/JavaScript. Six activities correctly have no configured
  facilities. Product catalogue uses the actual 21 development Products.
- Complete Edge workflow audit passed against disposable PostgreSQL records.

Additional booking probes found a gap beyond the existing suite: confirming a
draft social booking did not revalidate its existing roster's daily limits.
An existing member could therefore gain a third confirmed play. Independent
booking/participant writes also lacked serialization of the daily count, and
participant validation errors were not rendered in the detail page.

## Focused correction

Isolated checkout:
`C:\Users\utkarsh\Desktop\odoo hackathon nirbhay\.booking-limit-verification-1126140`

Branch: `feature/booking-limit-verification`, based on actual merged main.

- Booking confirmation validates all existing roster members as well as the
  primary booker, counting each member once per confirmed booking/local date.
- Booking and participant saves are atomic. Existing Booking rows lock first,
  followed by relevant Member rows ordered by primary key, before validation.
  Separate reservations/roster additions therefore serialize each member's
  last daily play. Primary participant creation rolls back with its booking.
- Participant saves reload the locked parent instead of trusting an old draft
  object when confirmation races the addition.
- Participant form field/non-field errors are escaped and displayed in the
  existing frontend layout. Plain/structured service validation errors are
  handled without assuming every error has a field dictionary.

Files: `club/models.py`, `club/views.py`,
`frontend/templates/club/booking_detail.html`,
`club/tests/test_booking_daily_limits.py`, and this report.
No model fields, migrations, settings, infrastructure or commerce services were
changed. Nayan/Pratik should review this narrow booking/form correction.

## Verification after correction

Python 3.13.7 / Django 5.2.19 / PostgreSQL 16.16:

- New daily-limit tests: **11 passed**, including three real independent-
  connection concurrency tests for booking, roster, and confirmation/add races.
- Complete suite: **237 passed**, zero failures/errors/skips, including all
  original commerce inventory/concurrency checks.
- Four supplemental PostgreSQL probes: all passed after correction. Before
  correction, the draft-roster probe failed and demonstrated three plays.
- **Two Edge browser audits passed** on the correction checkout: complete
  scheduled-plan/member-sale/reporting workflow, plus registration, booking
  conflicts, third-play rejection, visible roster errors, cancellation freeing
  the play limit, product search, guest checkout, insufficient-stock feedback,
  same-Sale retries, stock restoration, CSRF403 and isolated admin login.
- Mobile390x844 had no page overflow or JavaScript errors; validation screenshot
  was visually inspected. The audit-only admin/password exists only in the
  disposable test database, not development data or the repository.
- System/migration consistency and whitespace checks passed.

The first supplemental browser attempts had audit locator/text expectations
that did not match icon-bearing button names and the actual insufficient-stock
message. Those audit expectations were corrected outside the repository; the
final full audit passed. No passing result is inferred from those attempts.

Commands executed with the existing external verification Python:

```text
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py migrate --plan
python -B manage.py test --verbosity 1 --noinput
python -B manage.py test club.tests.test_booking_daily_limits --verbosity 2 --noinput
python -B <external booking-probes script>
python -B <external supplemental-browser.py>
python -B <external complete-workflow/browser-audit.py>
git diff --check
```

Tests/browser writes used separate disposable `test_champions_club` databases,
removed by Django. Existing development Product/Member/Plan/Court/Sale/SaleItem
and auth row counts/hashes were verified unchanged; all 25 migrations remain
applied. No persistent demo transactions were created. Docker's original
`commerce-integration-9243d85_postgres_data` volume is preserved.

## Scope and remaining review

Supported booking workflows use complete model saves through the existing
views/forms/admin and the locking paths above. Direct queryset updates, bulk
writes and partial `save(update_fields=...)` writes are outside this validated
booking interface; the existing UI uses full saves. PostgreSQL's GiST constraint
still independently protects overlapping stored confirmed ranges.

Core flows are verified locally on the correction branch. This correction must
be reviewed/merged before claiming the roster/daily-race fixes are on GitHub
main. It does not automatically merge or push directly to main.

The localhost development server was restarted from this correction checkout
with explicit `DEBUG=True`. Dashboard, counter, members, bookings, availability
and both main static assets were verified200 after restart. Existing development
records were retained; no persistent booking was manufactured for the demo.

Existing reporting limits remain: trends use sale creation dates, category
totals follow current Product categories, and new-draft request deduplication
is not implemented. Tabs, tables, delivery, enquiries/payroll are outside the
core implemented demo. Python3.12/deployment were not verified.

Local static serving requires process-local `DEBUG=True` for this localhost
development run. The inherited shell value `DEBUG=release` disables Django's
development static handler; published frontend files must not be replaced to
work around it.
