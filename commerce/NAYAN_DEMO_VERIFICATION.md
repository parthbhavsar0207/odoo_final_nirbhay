# Nayan frontend demo checkpoint - 2026-11-22

The user instructed using Nayan's latest frontend without combining or restoring
the custom staff-login implementation. Current main76ffec2 already has that
login reverted and Nayan's redesigned dashboard merged. PR19 is closed; the
authentication/compatibility branches remain preserved as separate worktrees.

Active demo checkout:
`C:\Users\utkarsh\Desktop\odoo hackathon nirbhay\.nayan-demo-backend-76ffec2`

Branch: `feature/nayan-demo-backend`, based on actual main76ffec2.

## Review and change

Nayan's grouped navigation, dashboard cards, recent bookings, membership tiers,
inventory alerts and sales-performance sections already use the real shared
backend. Existing routes support booking/payment feedback, receipts, CSV export,
product catalogue and guest/member counter workflows. No replacement backend,
new model, migration or additional framework was needed.

One backend defect was fixed in `frontend/views.py`: court utilization now counts
only confirmed active-court intervals clipped to06:00-22:00. Retired courts and
off-hours reservations cannot inflate the percentage. Added three meaningful
dashboard regressions and updated existing assertions to Nayan's current labels
and inventory-admin links. All frontend templates and CSS/JS remain byte-identical
to main. No custom auth middleware/settings/templates were applied.

Default test discovery was broken by upstream `club/tests.py` alongside the
existing `club/tests/` package. Its seven payment tests were preserved unchanged
as `club/tests/test_booking_payments.py`; both test sets now execute.

## Executed verification

Python3.13.7 / Django5.2.19 / PostgreSQL16.16:

- Full suite: **247 passed**, zero failures/errors/skips.
- Django system and migration consistency checks passed; all26 existing
  migrations applied, none pending. No schema or persistent business data writes.
- Current-flow Edge audit: **1 passed** on disposable test records. Actual AJAX
  booking success200, conflict400, receipt, export and cancellation verified.
  Guest total25.00, Silver bar total95.00 and dashboard completed120.00 verified.
  Cancellation restored both product stocks10->8->10. Missing CSRF rejected403.
- Read-only local Edge demo audit: **1 passed**. Dashboard opens directly without
  staff login, all three grouped menus work, catalogue shows21actual Products,
  mobile390x844 navigation works with no page overflow or JavaScript errors.
- Eleven live pages/assets returned200 without login redirects.
- Product, Member, Plan, Court, Sale and SaleItem row counts/hashes remain
  unchanged. While the live demo was running, a booking was submitted through
  the actual booking form: one confirmed booking and its participant now exist.
  Those records were retained. Test/browser-audit transactions stayed in the
  disposable test database. Other worktrees and credentials were not overwritten;
  the original PostgreSQL volume is preserved.

An older browser script initially expected the previous booking button text and
page navigation. Nayan's actual form uses a dynamic price button and AJAX success
modal; the current-flow audit exercised those real controls and passed.

Commands executed:

```text
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py migrate --plan
python -B manage.py test --verbosity 1 --noinput
python -B <external nayan-demo/current-workflow-audit.py>
git diff --check
```

The localhost server runs this checkout with `DJANGO_DEBUG=True` at
http://127.0.0.1:8000/. Counter, member and booking screens open directly as
requested. The existing Django admin retains its normal account login.

Publish only this small backend/test correction for review; do not merge the
closed custom-login compatibility PR or alter Nayan's frontend design.
