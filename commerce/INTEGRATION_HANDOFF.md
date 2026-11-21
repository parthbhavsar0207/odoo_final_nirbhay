# Commerce integration checkpoint — 2026-11-21

> Updated verification: Docker/WSL are installed, PostgreSQL 16.16 is healthy,
> both commerce migrations applied, and all 78 commerce tests passed. See
> [POSTGRES_VERIFICATION.md](POSTGRES_VERIFICATION.md) for the actual environment,
> commands, admin inventory fix and remaining dependencies. The checkpoint
> below records the earlier pre-foundation state and has been preserved.

Utkarsh owns this app. Follow INTEGRATION_CONTRACT.md; preserve all uncommitted
commerce work on `feature/utkarsh-commerce`.

## Verified state

- Fetch succeeded. Local `main`, the commerce branch and `origin/main` are at
  `0e906afd`. Origin exposes only `main`; every branch tree contains only the
  original two documentation files. No Django foundation is available there.
- Product and guest Sale/SaleItem are prepared locally. Migration chain:
  `commerce.0001_initial` -> `commerce.0002_guest_sales`; no core dependency.
  Offline consistency passed. Neither migration has been applied here.
- 45 database-free tests passed on isolated Python 3.13.7 / Django 5.2.19.
  Model/admin, syntax and offline migration checks passed. This is not a shared
  project or PostgreSQL verification. No ORM or transaction code changed at this
  checkpoint; only this handoff file was added.
- 30 database tests remain unexecuted: 8 Product, 18 guest-sale and 4 concurrency.
  There is no shared database configuration; Docker and psql are absent on PATH.

## Required from Parth

Provide the foundation branch/commit, agreed app import layout and registration,
team Django version/dependencies, PostgreSQL 16 Compose/environment setup, and
actual startup/migration/test commands. Confirm a safe development database and
separate disposable test database with creation permissions. Confirm compatibility
with the prepared migration syntax; do not change framework versions silently.

Run the following inside that actual shared environment, after confirming the
development database target. These commands have NOT been executed here:

```text
python -m django --version
python manage.py check
python manage.py makemigrations commerce --check --dry-run
python manage.py shell -c "from django.db import connection; assert connection.vendor == 'postgresql'; connection.ensure_connection(); assert connection.pg_version // 10000 == 16; print('PostgreSQL', connection.pg_version)"
python manage.py showmigrations commerce --plan
python manage.py migrate commerce --plan
python manage.py migrate commerce
python manage.py test commerce.tests.test_database commerce.tests.test_sales_database commerce.tests.test_sales_concurrency --verbosity 2
```

Expected: both commerce migrations apply and all **30 tests pass with zero
skips**. Verify rollback after a post-deduction failure, repeated completion,
concurrent last-item sales, repeated/concurrent cancellation, and completion
racing cancellation. Run `python manage.py test commerce.tests` for all 75 tests.
Do not reset shared data or treat SQLite/skipped tests as PostgreSQL success.

## Required from Nayan

Provide actual Member/Plan model locations, app label, migration names and plan
relation; exact shop/bar discount fields, units and valid ranges; agreed demo
values; expiry, suspension and inactive-plan eligibility semantics. Then add the
optional shared Member FK with the real migration dependency and discount tests.
Guest integration can proceed independently; member discounts remain deferred.

Next action: obtain Parth's runnable foundation and execute the commands above.
