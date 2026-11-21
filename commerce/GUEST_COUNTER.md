# Guest-counter backend handoff — Utkarsh to Pratik

## Scope

This milestone adds one active Product line per guest draft: select a product,
enter quantity, choose payment method, create draft, then explicitly complete or
cancel that Sale. Existing services own snapshots, amounts and stock writes.
Guests have zero membership discount. No member link, new migration, inventory
editing, templates or shared infrastructure is introduced.

The working integration path is:
`C:\Users\utkarsh\Desktop\odoo hackathon nirbhay\.commerce-integration-9243d85`.
It remains detached at foundation commit `9243d85`. The original source branch
is `feature/utkarsh-commerce`. Remote `origin/main` was fetched and inspected at
`a3bfa7b`, including Nayan's actual Member/Plan models and `club.0002_initial`.
Those updates were not merged here or applied to the development database.
Member sales/discounts stay deferred for this guest-only milestone.

## Exact routes

Parth's existing root URL configuration mounts `commerce` at `/commerce/`.

| Named URL | Path | Methods | Result |
| --- | --- | --- | --- |
| `commerce:guest_counter` | `/commerce/counter/` | GET, HEAD | Show guest form/catalog context. |
| `commerce:sale_create` | `/commerce/sales/create/` | POST | Create one guest draft, then redirect to its detail. |
| `commerce:sale_detail` | `/commerce/sales/<pk>/` | GET, HEAD | Show persisted sale/items and action context. |
| `commerce:sale_complete` | `/commerce/sales/<pk>/complete/` | POST | Complete using the service, then redirect to detail. |
| `commerce:sale_cancel` | `/commerce/sales/<pk>/cancel/` | POST | Cancel using the service, then redirect to detail. |

`pk` is the existing positive Sale primary key, supplied in the URL. Mutating
routes do not accept a caller-supplied status or Sale ID in the POST body. Success
uses Django's named redirect (302) to `commerce:sale_detail`; arbitrary `next`
values are ignored. The existing `commerce:index` and `commerce:shop` placeholders
are retained; they are not sale mutation endpoints.

All five new routes use `staff_member_required(login_url="admin:login")`:
authenticated, active staff are allowed; anonymous, nonstaff and inactive users
are redirected to `/admin/login/?next=...`. This reuses the installed Django admin
login and session middleware; no second authentication flow or new permissions
model is created. All active staff can operate any guest Sale in this MVP.
Unchanged legacy shop/index access is outside these new counter operations.

For authenticated staff, inappropriate methods return 405. Global CSRF middleware
and explicit `csrf_protect` protect all writes. Missing/invalid CSRF tokens return
403 before mutations. Display routes ensure a CSRF cookie is available.

## Form contract

`commerce.counter_forms.GuestSaleForm` is separate from ProductForm to keep the
Product-only slice separable. POST to `commerce:sale_create` with exactly:

| Field | Input | Validation |
| --- | --- | --- |
| `product` | Product ID | Required ModelChoiceField; only existing active Products. |
| `quantity` | Whole quantity | Required IntegerField; 1 through 2147483647. |
| `payment_method` | Choice string | Required; exactly `cash`, `card` or `UPI`. |

Include `{% csrf_token %}` in each HTML POST form. The create form must post all
three fields above. Complete/cancel forms need only CSRF; their action URL carries
`sale.pk`. HTMX requests must submit the same token/header and fields. Redirect
responses are ordinary Django redirects; no separate API response contract exists.

There are no form fields for price, discount, total, member or stock. Extra input
cannot override service amounts. Creation makes a draft without reserving stock:
the form validates product/input shape, and completion revalidates locked stock
and active status through `complete_sale`. An unavailable quantity therefore
returns a conflict at completion rather than a misleading reservation guarantee.

Two create requests create two drafts. Request-level duplicate-draft prevention
is explicitly NOT implemented (and a focused test records this limitation).
Completing/cancelling the SAME Sale ID is idempotent through the existing services.

## Template and context contract

Every normal counter/detail/error screen reuses **`commerce/index.html`**.
No template file changed. The current scaffold shows only its old catalog and
disabled buttons; it does not yet render the new form, Sale or error context.
The backend is callable and tested, but the clickable staff workflow requires
Pratik's template work.

| Context key | Value |
| --- | --- |
| `page_title` | `Guest Counter` or `Guest Sale #<pk>`. |
| `products` | QuerySet of active Product records, existing Product ordering. |
| `form` | GuestSaleForm, unbound normally; bound with field/nonfield errors after invalid creation. |
| `sale` | Sale instance on detail/action-conflict screens; otherwise `None`. |
| `sale_items` | Sale items with selected Product, existing item ordering; otherwise empty list. |
| `error_message` | Escapable validation message on completion/cancellation conflict; otherwise `None`. |

Pratik implements two modes in the existing template:

1. With `sale is None`, render `form`, its errors and a POST create button. Link
   navigation/New Sale to `{% url 'commerce:guest_counter' %}`.
2. With a Sale, render status, payment method and persisted monetary snapshots;
   item rows use `quantity`, `unit_price`, `discount` and `line_total`. Draft amounts
   are zero placeholders until completed; label them accordingly. Add distinct
   POST actions to named complete/cancel URLs. Draft: complete or cancel;
   completed: cancel; cancelled: no mutation buttons. Backend still validates
   all statuses independently. Show `error_message` and form errors with default
   escaping, not `safe`.

Do not recalculate prices, infer discounts, overwrite stock or treat current
Product prices as historical SaleItem prices. No hardcoded URLs are needed.

## Failure behavior

| Failure | Response |
| --- | --- |
| Invalid product/quantity/payment or creation-time service validation | 400; same template, bound form/errors; no draft from a failed create. |
| Insufficient stock, inactive product at completion, cancelled Sale completion or other service validation | 409; same template, current Sale/items, `error_message`; no partial stock write. |
| Unknown Sale ID | 404 via Django's normal handler. |
| Wrong method | 405 for authorized staff. |
| Missing/invalid CSRF | 403 via Django's middleware. |
| Service/database failure | 503, generic `text/plain` message; no exception details or database requery for error rendering. |

Creation/completion/cancellation use the existing service transaction boundaries.
Database errors are logged server-side and never returned verbatim. After a 503,
staff should check the Sale status before retrying; new-draft requests are not
request-idempotent. Do not automatically resubmit a create after an uncertain
network result.

## Checks and pull-request separation

No model, service, calculation or migration changed. ProductForm, Product admin
stale-stock protection and all previous tests are retained. New code is confined
to `counter_forms.py`, additive counter views/routes, and `tests/test_counter.py`.
This document is the frontend handoff. Product-only review can use the Product
model/admin/form/migration/tests independently; later guest-sales review includes
Sale/SaleItem, `0002_guest_sales`, services/calculations and these counter files.
Do not include combined `models.py` wholesale in a Product-only PR: select its
Product definition and first migration. No PR, commit or push is created here.

From the integration worktree, use the verified external environment's Python
with process-local `DEBUG=True` and PostgreSQL target settings:

```text
python -B manage.py check
python -B manage.py makemigrations commerce --check --dry-run
python -B manage.py test commerce.tests.test_counter --verbosity 2 --noinput
python -B manage.py test commerce.tests --verbosity 1 --noinput
```

Executed on PostgreSQL **16.16** with Django **5.2.19** / Python **3.13.7**:
focused counter suite **27 passed**, full commerce suite **105 passed**, zero
failures/errors/skips. The full run includes all four concurrency tests and
three Product admin stock regression tests. System and migration-consistency
checks passed; no migration was added or applied in this milestone. Django
removed its disposable test database after both final test runs.

Focused tests cover form validation, staff access, HTTP methods, real ORM/service
changes, same-ID retry semantics, response status/context, safe redirects and
CSRF with enforcement enabled. Database-failure injection tests error handling;
it does not replace the normal PostgreSQL integration tests. Test-run results
are reported after execution, not inferred from prepared test code.

Next handoffs: Pratik renders the UI contract; Parth coordinates adopting latest
main without overwriting uncommitted commerce work; Nayan confirms discount
eligibility/ranges/rounding before the later member-linked sales milestone.

The development DB currently has the two commerce migrations but no `auth_user`
table. Parth must apply the project's existing shared/auth/session migrations and
provide a staff account for interactive login. No new authentication migration
or shared bootstrap change is made by this milestone. Tests applied the existing
shared migrations only in Django's disposable test DB. No development records
were added, and the original PostgreSQL container/volume remain healthy.
