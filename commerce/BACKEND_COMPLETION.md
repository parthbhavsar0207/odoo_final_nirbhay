# Shared frontend backend completion - 2026-11-22

The user authorized completing the identified membership, availability,
concierge and reporting gaps across the existing shared applications. The team
ownership contract remains unchanged. This builds on PR #12; it does not replace
Pratik's frontend or Utkarsh's tested counter implementation.

## Delivered behavior

- Membership plan forms/admin and `full_clean()` reject negative fees/court
  rates and shop/bar percentages outside Decimal 0.00 through 100.00.
- `MemberPlanChange` stores dated assignments, unique per member/date.
  `change_membership_plan()` locks Member then MembershipPlan inside one
  transaction, validates the active target and membership dates, and rejects
  duplicate or past effective dates.
- `Member.plan` remains the original assignment. Membership dates are not
  rewritten. `effective_plan_on_date(date)` selects the latest dated assignment
  on or before that date; `current_plan` resolves today. Future changes therefore
  preserve today's benefits. No scheduler or separate service is required.
- Booking pricing resolves the plan for the booking's club-local date; commerce
  completion resolves today's plan under the Member lock before locking the
  plan. Eligibility also requires a club member, valid dates, no suspension and
  an active plan. Ineligible profiles retain their link and use walk-in pricing
  or no commerce discount.
- Confirmed booking and completed sale monetary snapshots remain unchanged.
  Zero-price confirmed bookings are no longer repriced by later ordinary saves.
  The booking model rejects starts outside exact hour/half-hour boundaries.
- Member directory tier filtering, plan counts and dashboard eligibility use
  effective assignments. Future assignments remain visible even without a
  baseline plan. Member forms/admin cannot overwrite the baseline after a dated
  change; ordinary profile edits remain available.
- Public availability and activity details share full interval-overlap checks
  for 60-minute sessions starting every 30 minutes, 06:00 through 21:00, within
  the existing 22:00 closing time. Only confirmed bookings block sessions;
  adjacent endpoints are allowed, cancellations release them, and public cell
  payloads contain status only. PostgreSQL's existing exclusion constraint
  remains the authoritative overlap protection at confirmation.
- Concierge plan benefits, facility names and active shop/bar product counts
  come from current database records. Empty states no longer advertise
  unconfigured facilities.
- Dashboard totals use completed Sale/SaleItem monetary snapshots. Mixed sales
  count once overall, with shop/bar amounts split by line. Drafts/cancellations
  are excluded. Low-stock alerts, recent sales and seven-day totals are live.
  Confirmed Booking Value is explicitly separate from collected revenue.

## Existing interface and presentation

No URL names changed. Existing counter routes and GuestSaleForm/MemberSaleForm
continue to call commerce services; templates do not calculate prices or stock.
Counter access remains anonymous as explicitly requested, with POST-only writes
and CSRF protection. Product/admin authentication remains unchanged.

Frontend changes are confined to existing `frontend/templates/club/` and
`frontend/templates/dashboard/index.html`. The published colors, typography,
components and navigation are retained. Availability columns are driven by
`operating_hours`; dashboard adds the context from
`commerce.reporting.commerce_dashboard_summary()`.

No root `templates/` or `static/`, new framework, second database, infrastructure
configuration, duplicate membership model or commerce migration was added.

## Migration and development database

`club.0004_plan_validation_and_scheduled_changes` depends on the actual upstream
`club.0003_alter_court_sport_alter_membershipplan_tier`. Its validator alterations
are PostgreSQL schema no-ops; it creates the dated-assignment table, foreign keys
and unique constraint. It contains no data rewrite or destructive operation.

After checks/tests, it was applied to the verified existing local development
database `champions_club`, PostgreSQL 16.16 at `127.0.0.1:5433`. All 25 migrations
are applied; none remain pending. The new assignment table is empty. Existing
21 Products, 6 Members, 3 Plans, 5 Courts, 8 Sales, 8 SaleItems, 0 Bookings and
the existing auth account were hash-verified unchanged. No demo records were
created during this milestone. Docker volume
`commerce-integration-9243d85_postgres_data` remains intact.

Other 7 worktrees, their HEADs and 487 pre-existing files were hash-verified
unchanged. Local preservation hashes/screenshots are outside Git and contain no
credential material. Credentials remain private outside the repository.

The local development server was restarted from this completion checkout at
`http://127.0.0.1:8000/`, stopping only the verified prior Django listener.
Twelve read-only live page/API checks returned 200, including dashboard, members,
plans, bookings, availability, activities, both counter forms and current FAQ.
No persistent workflow/demo transaction was created by those checks.

## Executed verification

Python 3.13.7 / Django 5.2.19 / PostgreSQL 16.16:

- Focused `club.tests frontend.tests`: **55 passed**, no failures/errors/skips.
- Complete suite: **226 passed**, no failures/errors/skips, including the existing
  four independent-connection inventory concurrency tests.
- Final headless Microsoft Edge audit: **1 passed** using a disposable PostgreSQL
  test database and the actual Django templates/static assets.
- System checks, migration consistency and `git diff --check` passed.
- Migration SQL and development migration history inspected before applying
  only `club.0004`; final `migrate --plan` reports no pending operations.

Browser audit exercised invalid 101% rejection, valid Platinum creation, future
plan assignment preserving current Silver, 09:30 booking overlap blocking
09:00/09:30/10:00 while 10:30 remains bookable, future booking rate 125.00,
member shop/bar totals 180.00/95.00, dashboard sales 275.00 and separate confirmed
booking value 625.00. Cancellation restored stock 10 -> 8 -> 10 and removed
cancelled sales from totals. Concierge reflected current 200.00/125.00 court
rates. Mobile 390 x 844 had no page overflow and no JavaScript errors; screenshot
was visually inspected. Test/browser records remained in disposable test DBs.

Commands executed with the existing external verification Python from this
checkout:

```text
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py sqlmigrate club 0004
python -B manage.py migrate --plan
python -B manage.py test club.tests.test_booking_contract --verbosity 1 --noinput
python -B manage.py test club.tests.test_member_directory club.tests.test_availability --verbosity 1 --noinput
python -B manage.py test --verbosity 1 --noinput
python -B <external final-browser/browser-audit.py>
python -B manage.py migrate club 0004 --noinput
python -B manage.py test club.tests frontend.tests --verbosity 1 --noinput
git diff --check
```

External verification Python:
`C:\Users\utkarsh\AppData\Local\Temp\champions-commerce-verify-dbdc51fa63f24867be3f5c362bc67b46\Scripts\python.exe`.
This is a local test tool, not a new project dependency. Python 3.12 was not
verified.

## Review order and practical limits

This change is on `feature/team-backend-completion`, based on
`feature/utkarsh-frontend-backend` commit `682c1b3` (PR #12). Review the new branch
against that branch so the product-search/concierge connection is not duplicated.
Merge PR #12 first; then retarget this dependent PR to updated main and recheck
the diff/migration graph. No automatic merge or direct push to main is authorized.

Nayan reviews the dated resolver, booking safeguards and `club.0004`; Pratik
reviews the limited frontend/dashboard changes; Parth coordinates migration and
delivery order. There is no remaining local implementation/environment blocker
for these five requested gaps. Team review/merge remains pending.

Explicit limitations:

- Sales date reporting uses `Sale.created_at`, because there is no completion
  timestamp. The UI labels creation-date grouping accordingly.
- Category grouping uses current `Product.category`; money uses historical
  snapshots. Editing a product category can reclassify historical category
  totals. No category-history policy was invented.
- Plan range validators run in forms/admin/`full_clean()`; this migration does
  not add range CHECK constraints or validate arbitrary direct ORM updates.
- Scheduled assignments change which plan applies, not a frozen copy of plan
  benefits. Later plan edits affect later confirmations/completions. Past saved
  transaction money is preserved.
- New-draft request deduplication remains unimplemented. Repeated completion or
  cancellation of the same Sale ID remains atomic and idempotent.
- Membership renewal and editing/cancelling a scheduled plan change are outside
  this milestone. Use the scheduling service rather than direct ORM writes.
