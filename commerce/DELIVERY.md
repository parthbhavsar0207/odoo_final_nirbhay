# Commerce delivery — 2026-11-21

The user authorized finishing member integration, committing, pushing and
opening separate commerce PRs. No direct-main push or automatic merge occurred.

## Published PRs

Merge/review in this dependency order; retarget each dependent PR to main after
its predecessor merges.

| PR | Base | Scope |
| --- | --- | --- |
| [#6 Product](https://github.com/parthbhavsar0207/odoo_final_nirbhay/pull/6) | main | Product, validated form/admin, independent0001 and Product tests |
| [#7 Guest backend](https://github.com/parthbhavsar0207/odoo_final_nirbhay/pull/7) | feature/utkarsh-product | Sale/SaleItem, atomic services, staff counter forms/routes,0002 and tests |
| [#8 Frontend connection](https://github.com/parthbhavsar0207/odoo_final_nirbhay/pull/8) | feature/utkarsh-guest-sales | Pratik's current frontend templates/assets and protected catalog aliases |
| [#9 Member sales](https://github.com/parthbhavsar0207/odoo_final_nirbhay/pull/9) | feature/utkarsh-commerce-ui | Real club.Member FK, configurable shop/bar benefits, member form/routes,0003 and tests |

Current working checkout:
C:\Users\utkarsh\Desktop\odoo hackathon nirbhay\.commerce-publish-c76a895
Branch: feature/utkarsh-member-sales.
Base main: c76a8950df8c28bac17d4605a34abd8cc14d64cb.

Merged upstream frontend cleanup is preserved. All templates/assets remain
inside frontend/; no obsolete03-frontend.patch/root templates/static restored.
No shared settings, Docker configuration, Nayan model or existing migration
was modified. Member migration0003 depends on real club0002 and commerce0002.

Commits use Utkarsh's authenticated GitHub account noreply identity. No global
Git identity was changed. Original source/review/integration worktrees and
patch-preparation artifacts remain untouched.

## Executed verification

Actual PostgreSQL16.16, Django5.2.19, Python3.13.7:
- Product stage:21 passed.
- Guest backend stage:105 passed.
- Connected latest frontend:121 passed.
- Member integration focused:30 passed.
- Final complete suite:151 passed,0failures/errors/skips, including5 concurrency
  tests and stock/admin rollback/idempotency coverage.
- Guest Edge browser audit:1 passed, stock10->8->10,total25.00, errors/CSRF/mobile.
- Member Edge test-DB audit:1 passed; shop subtotal25.00/discount2.50/total22.50,
  bar subtotal2.40/discount0.12/total2.28, stock10->8->10 and mobile390x844.
- Persistent member Edge rehearsal: passed with existing utkarsh_counter login,
  Sale#7 total22.50/discount2.50, stock10->8->10; cancellation record retained.
- System check, all-app migration consistency and Git whitespace checks passed.
- Tests created/migrated/removed separate test_champions_club database.
- Python3.12 has not been separately verified.

Executed commands used the previously documented external Python:
manage.py check; makemigrations --check --dry-run; test commerce.tests at
Product/guest stages; test commerce.tests.test_member_sales; test for full suite;
migrate commerce --plan; migrate commerce --noinput; migrate --plan.
Browser scripts/screenshots are external local audit artifacts, not dependencies
or application infrastructure.

## Local demo

http://127.0.0.1:8000/commerce/counter/
Member purchase: http://127.0.0.1:8000/commerce/counter/member/

Development server now runs from the publish checkout, replacing only the
previous verified local manage.py process. Existing staff account/password
remains unchanged. The DPAPI-encrypted credentials remain outside Git at:
C:\Users\utkarsh\.codex\private\champions-club-counter.credentials.xml.

Applied additive commerce.0003_sale_member to the verified development database.
All23 migrations are applied; none remain pending. Existing commerce history
and original PostgreSQL volume are retained.

For member demo, created only missing shared records using published illustrative
Silver values (shop10%,bar5%) and reserved member name CC DEMO - Silver member.
No existing Member/Plan was overwritten and no duplicate model was introduced.
This is demo data, not official pricing. Product final stocks remain10/10/2.
Cancelled guest/member rehearsal sales remain as audit history.

## Remaining team work

Member policy/form/routes are specified in MEMBER_SALES.md. Pratik reviews the
frontend integration and adds dashboard aggregates from completed Sale/SaleItem
records; confirmed booking value must not be labelled collected revenue.
Dashboard code was not modified here.

Parth coordinates PR dependency order and team startup/seed delivery. These PRs
are published for review, not merged. Main still needs the commerce changes
merged before other teammates see working commerce on main.

Sale monetary snapshots survive later Product/Plan changes. Names/categories
remain current related fields; agree category-history behavior before reporting
over category edits. Request-level duplicate draft creation is still not
idempotent; completion/cancellation for the same Sale are idempotent.
