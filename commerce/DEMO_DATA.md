# Demonstration data setup

The repository now includes a shop/bar catalogue seed command:

```text
python manage.py seed_commerce_data
```

It creates 18 illustrative Product records: 10 shop items and 8 food/drink
items. These are configurable demonstration prices, not official club rates.
The command uses the existing PostgreSQL connection, ORM validation and a
transaction advisory lock. It creates only missing names, preserves all existing
prices/stock/thresholds/active flags, and aborts duplicate-name or category
ambiguity before creating records. Names are not globally unique: run one
coordinated seed operator and avoid manual creation of these names concurrently.

Existing products and Sale/SaleItem history are never deleted or reset.
Repeated setup after completed sales must preserve deducted inventory and
snapshotted prices. The six PostgreSQL tests verify these rules.

## Current local data

After the user reported missing catalogue/member data, the verified development
database champions_club was populated without overwriting existing records:

- 21 Products: 18 new catalogue items plus the original 3 retained test products.
- 6 Members: the 5 published Nayan demo profiles plus the retained Silver demo.
- 3 plans: Gold, Silver, Junior with the published illustrative benefits.
- 5 published courts.

Nayan's existing seed_club_data definitions supplied those Member/Plan/Court
records. Only absent records were inserted; existing Silver/demo profiles and
all inventory/sale records were preserved. Nayan's command itself was not run
because it uses update_or_create and can replace existing values. No club model,
view, template or seed-command file was modified by this change.

The original before-population business records were snapshotted locally and
verified unchanged after insertion. No migration, booking or revenue record was
fabricated. Existing drafts, including Sale8 for 55 units of a stock-2 test
product, remain unchanged and cannot complete when stock is insufficient.

## Where to see it

- Product catalogue: /commerce/counter/
- Members: /club/members/
- Member sale form: /commerce/counter/member/

A /commerce/sales/<id>/ address shows one draft/transaction, not the whole
catalogue. Draft amounts remain Pending until the completion service snapshots
prices and discounts; catalogue prices are visible on product cards.

## Executed validation

PostgreSQL16.16, Django5.2.19:
- Seed command run twice: first18 inserted, second0 inserted.
- Missing published club records loaded twice: second0 inserted.
- Six seed tests passed.
- Complete suite158 passed,0failures/errors/skips.
- System/migration consistency checks passed; no schema change.
- Read-only Edge checks confirmed21 live cards,6 member selector choices and
  successful catalogue/member pages. Original stock and sale data preserved.

Only commerce management command/test/document files changed. Frontend design,
business services and teammate code are unchanged.
