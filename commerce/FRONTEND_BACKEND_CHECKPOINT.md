# New frontend/backend checkpoint — 2026-11-22

> The user subsequently authorized completing the gaps listed below. See
> [BACKEND_COMPLETION.md](BACKEND_COMPLETION.md) for the implemented dated plan
> changes, availability, live FAQ, dashboard, applied club.0004 and executed
> 226-test/Edge verification. This checkpoint preserves the earlier PR #12 state.

Base main b463606f76c52418adc0c5df39b550b6e41df882. Active worktree:
C:\Users\utkarsh\Desktop\odoo hackathon nirbhay\.commerce-frontend-backend-b463606
Branch feature/utkarsh-frontend-backend.

## Repository review

The latest frontend already has Django backends for:
- Activities directory/details and real Court facility queries.
- Plan list/create/edit/toggle/public list.
- Member plan change form and member/booking list filters.
- Header suggestions querying real active Products/Courts/Plans.
- Concierge FAQ responses.
- Guest/member counter routes, form validation and transaction services.
- Custom dropdowns preserving native Django form values.

Those routes were not rebuilt. New club.0003 expands sports/tiers only; commerce
already uses configurable percentage fields regardless of tier.

## Connections fixed

Header product suggestions previously all opened /commerce/ and lost the item.
Product.get_absolute_url now uses the named guest counter with
?product=<id>#guest-sale-form. The suggestion API uses this Product method.

Guest/member GET views validate that optional Product ID, preselect the actual
active Product and set quantity1. Missing/inactive/malformed IDs return404
without creating sales or modifying inventory. POST uses validated submitted
fields and does not trust query-string prices/products.

The new concierge's Pro Shop chip sends commerce, absent from its FAQ keywords.
Added commerce/cafe/cafeteria keywords so it returns the existing commerce answer.

Files changed:
- commerce/models.py: URL method only, no database field.
- commerce/views.py: GET preselection in existing guest/member views.
- club/views.py: two small commerce connection lines, suggestion URL and FAQ
  keywords; no member/booking rules changed.
- commerce/tests/test_catalog_links.py:13 meaningful PostgreSQL tests.
- This document.

Frontend templates/CSS/JS, transaction services, migrations and settings are
unchanged. Only new frontend/ architecture is active. Anonymous counter access
requested earlier remains; CSRF and HTTP method restrictions remain enforced.

## Executed verification

PostgreSQL16.16 / Django5.2.19 / Python3.13.7:
- Baseline on latest main:158 tests passed.
- Final focused search/counter/UI/member tests:87 passed.
- Complete final suite:171 passed,0failures/errors/skips.
- System check clean; migration consistency no changes detected.
- Microsoft Edge audit:1 passed; all15 requested new/shared screen routes200.
- Header search fetched actual Product suggestions and clicked through to the
  selected product/quantity1 in the new dropdown.
- Custom Product/Member/UPI controls submitted the correct actual form values.
- Concierge chip displayed the commerce answer.
- Guest sale total200.00; configured Platinum member bar total94.00;
  stock10->8->10, mobile390x844 no page overflow, zero JavaScript errors.
- New tests verify added tiers, plan-form edits affect later sales only, private
  member fields absent from public search, invalid IDs and CSRF protection.
- Test runner migrated/removed separate test_champions_club; no browser-test
  transactions were added to the development database.

Initial browser audit reproduced the commerce-chip fallback; its expected
answer timed out. The keyword fix made the final audit pass.
No Python3.12 verification claimed.

Commands executed with the existing external Python:

```text
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py migrate --plan
python -B manage.py test commerce.tests.test_catalog_links commerce.tests.test_counter commerce.tests.test_counter_ui commerce.tests.test_member_sales --verbosity 1 --noinput
python -B manage.py test --verbosity 1 --noinput
```

External Edge script/screenshots are local audit artifacts, not application
dependencies.

## Nayan/Pratik findings for coordination

These exist in their modules and were inspected read-only:
- MembershipPlanForm permits negative fees/rates and discount values outside
  0..100. Commerce rejects invalid applied discounts before deductions, but
  plan input needs validation.
- Future effective plan date immediately replaces Member.plan and
  membership_start, removing current benefits until then; no scheduled
  transition exists.
- Availability uses whole-hour buckets. A09:30–10:30 booking may leave10:00
  falsely free. Grid availability needs full60-minute overlap checks for starts
  every30minutes.
- Booking pricing omits plan.active/is_club_member checks used by commerce.
- FAQ hardcodes membership discounts/Silver150 court rate, differing from
  published seed200; values become stale when plan management edits them.
- FAQ describes all10 sports as available even when those Court facilities
  are not configured; activity detail already displays the honest empty state.
- Dashboard omits completed commerce totals and calls confirmed booking value
  revenue. Real Sale/SaleItem reporting data is ready.

Nayan/Pratik should review the two minimal shared suggestion/FAQ lines and fix
their remaining business/reporting issues independently.

## Preservation and local setup

All original worktrees, uncommitted source files and PostgreSQL volume remain.
Development counts before integration:21Products,6Members,5Courts,8Sales.
Applied only the existing upstream club.0003 choices migration; all24 current
migrations are now applied, with no pending operations. Started the local
development server from this checkout at127.0.0.1:8000. Live HTTP checks confirmed
Activities200, Product search links with selected IDs, counter200 and the
concierge commerce response. Product/member/court/sale counts remain21/6/5/8.
No new commerce migration, infrastructure, member model or API server added.
