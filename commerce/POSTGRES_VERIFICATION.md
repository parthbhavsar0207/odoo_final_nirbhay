# PostgreSQL commerce verification — 2026-11-21

## Verified environment

- Source branch remains `feature/utkarsh-commerce` at `0e906afd`, with all
  existing uncommitted commerce work retained. No commits or pushes.
- Integration worktree: `C:\Users\utkarsh\Desktop\odoo hackathon nirbhay\.commerce-integration-9243d85`,
  detached at Parth's merged foundation commit `9243d85`.
- Docker Desktop was missing. The requested WinGet installation succeeded:
  `winget install --exact --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements`.
  Installed Desktop 4.99.0, Docker Engine 29.9.3 and Compose v5.7.0.
- WSL was missing. Both `wsl --install --no-distribution` and its
  `--web-download` variation failed with HTTP 403. The supported standalone
  Microsoft WSL 3.0.5 x64 MSI succeeded with `/qn /norestart`, after validating
  its published SHA-256 and Microsoft signature. WSL 2 and Docker's distro are
  running. User approved administrator/UAC installation; Windows was not rebooted.
- Docker had no existing containers or volumes. Port 5433 was free. Parth's
  unchanged Compose file created `champions_club_postgres` and
  `commerce-integration-9243d85_postgres_data`. No existing data was removed.
- PostgreSQL **16.16** (`server_version_num=160016`) is healthy. Django connected
  through **127.0.0.1:5433**, using the configured development credentials.
  Database `champions_club` was empty before migration, with no migration history
  or pre-existing `test_champions_club` database. The role can create test DBs.
- Tests used the existing external virtual environment:
  `C:\Users\utkarsh\AppData\Local\Temp\champions-commerce-verify-dbdc51fa63f24867be3f5c362bc67b46\Scripts\python.exe`.
  Runtime Python 3.13.7, Django 5.2.19, with Parth's requirements installed.
  Parth's README targets Python 3.12; that runtime has not been tested here.

## Executed commands and results

From the integration worktree, `docker` below was invoked by its installed
absolute path `C:\Program Files\Docker\Docker\resources\bin\docker.exe`:

```text
docker version
docker compose version
docker context ls
docker ps -a
docker volume ls
docker compose config --format json
docker compose up -d db
docker compose ps
docker exec champions_club_postgres pg_isready -U postgres -d champions_club
python -B manage.py check
python -B manage.py makemigrations commerce --check --dry-run
python -B manage.py showmigrations commerce --plan
python -B manage.py migrate commerce --plan
python -B manage.py migrate commerce
python -B manage.py test commerce.tests.test_sales_concurrency commerce.tests.test_database commerce.tests.test_sales_database --verbosity 2 --noinput
python -B manage.py test commerce.tests.test_product_admin --verbosity 2 --noinput
python -B manage.py test commerce.tests --verbosity 2 --noinput
```

The actual Django environment was used throughout. A read-only Django ORM/SQL
probe verified server version, authenticated host connection, empty development
database, migration history and test-database permissions before mutation.

- Both `commerce.0001_initial` and `commerce.0002_guest_sales` applied successfully.
- All **30 original PostgreSQL tests passed**, including all four concurrency
  tests, with zero failures/errors/skips. This verifies real row locking,
  completion retries, stock contention, rollback and duplicate cancellation.
- The new Product admin regression suite first ran 3 tests: **1 passed and 2
  failed**, reproducing stale-stock overwrite. After the fix, the full suite
  ran **78 tests: all passed, zero failures/errors/skips**. This comprises 45
  database-free tests and 33 PostgreSQL tests.
- Project system checks passed; no model/migration changes were detected.
- Development migration history was checked again and is consistent. Only the
  two commerce migrations are applied to the development DB. Django applied all
  shared/core/auth migrations inside its separate test database while testing.
- Django removed the disposable test database after each run. Final development
  Product/Sale/SaleItem counts remain zero. The PostgreSQL volume remains intact
  and the container remains healthy/running.

## Commerce defect fixed

Previously, a stale Product admin form could overwrite a checkout deduction:
load stock 10, complete a sale leaving 8, save the old price-edit form and restore
stock to 10. The regression test reproduced this with real PostgreSQL writes.

`ProductAdmin.get_readonly_fields()` now makes stock read-only for existing
products. `save_model()` writes only changed non-stock fields, preserving stock
deducted by checkout. New-product creation still accepts initial stock. Three
new tests exercise those paths. No model, migration or sale-service change was
needed. Future catalog update views must use the same safe stock-edit discipline;
direct absolute stock overwrites are not a supported inventory adjustment flow.

All original 19 files remain. `admin.py` contains the tested inventory fix and
`INTEGRATION_HANDOFF.md` has a pointer to this report; the other 17 original files
are unchanged. Added this report and `tests/test_product_admin.py`. Source and
integration copies match. No settings, Compose, core models or templates changed.

## Remaining handoff

The original source branch still lacks Parth's foundation locally; continue
integration testing in the existing combined worktree. Merge preparation must
preserve the uncommitted commerce files and the tested fix.

Nayan's Member/Plan models are still placeholders in this foundation. Member
sales/discounts remain deferred until the real models, migration dependency,
field units and eligibility semantics arrive. Guest sale creation is idempotent
only when retrying completion/cancellation for the same Sale ID; request-level
draft creation idempotency and named route/form/context handoff remain future
commerce work. No duplicate membership or payment models were created.

Next safe commerce milestone: agree staff access and request-idempotency behavior,
then expose guest-counter backend routes/forms for Pratik using the tested
services. Keep frontend templates in Pratik's ownership.
