# Staff authentication - 2026-11-22

The user explicitly replaced the earlier anonymous counter demo policy: knowing
a URL must not grant access to club records. This change is based on merged main
`03ac11f` (including PRs #12 through #15), in the isolated
`.staff-authentication-03ac11f` checkout on `feature/staff-authentication`.

## Implemented access

One Django authentication system uses hashed passwords and server-side sessions.
There is no new customer/auth model, API server or frontend framework.

| Role | Allowed operational access |
| --- | --- |
| Owner | Dashboard, memberships/plans, bookings, receipts/exports and commerce. |
| Reception | Member records, dated plan assignment, bookings and booking receipts/exports; no owner dashboard or sales. |
| Counter | Guest/member sales, sale snapshots/receipts, completion/cancellation; no member directory, booking export or owner dashboard. |

An account must be authenticated, active, staff, and hold every required Django
permission. Merely setting `is_staff` does not grant operational access. Groups
provide the permission sets; superusers retain Django's existing full access.
Counter staff may select the shared Member and view the member identity on their
sales as required for discounts, but cannot browse the full member directory.

`config.access.StaffAccessMiddleware` checks named routes before their views or
business queries run. Anonymous requests redirect to login, authenticated but
unpermitted requests return403, and unknown new application routes fail closed.
The policy includes HTML/JSON booking details, both export aliases, booking/sale
receipts, member pricing API and every counter mutation. Templates hiding links
are presentation; server-side checks are the access boundary.

Safe public GET/HEAD routes: Activities/detail, public plan catalogue, privacy-
preserving availability, public suggestions and FAQ. These do not expose Member
identity or private transactions. Search suggestions show catalogue prices but
no exact stock quantities. Public reserve controls route visitors through the
protected booking form/login. POSTs to these public read endpoints return405.
The existing Pro Shop link currently opens protected counter login; a separate
public product-only screen is outside this authentication slice.

## Login/session interface

| Name | Path | Methods |
| --- | --- | --- |
| `staff_login` | `/accounts/login/` | GET/HEAD form, POST username/password/CSRF/optional next |
| `staff_logout` | `/accounts/logout/` | POST with CSRF; removes session |
| `staff_home` | `/accounts/` | GET/HEAD; chooses permitted role landing |

The existing `/` dashboard is protected. Staff login rejects inactive and
nonstaff accounts. Django validates same-host `next` values; a next page outside
the account's permissions falls back to the assigned role landing. Login/logout
and private responses have no-store/private cache controls. Logout GET is405.
State-changing counter requests remain POST-only and CSRF protected.

Session cookies are HttpOnly and SameSite=Lax, expire after one hour and on
browser close. Session and CSRF cookies use Secure when DEBUG=False. Localhost
uses explicit `DJANGO_DEBUG=True`; deployed HTTPS configuration is required for
Secure cookies. The session contains an account ID, not a plaintext password.
There is no self-registration endpoint that can create staff users.

## Account provisioning

Use the existing Django administrator rather than putting passwords in Git:

```text
python manage.py migrate
python manage.py setup_staff_roles
python manage.py createsuperuser
```

Run `createsuperuser` interactively only when a trusted administrator is needed;
keep its credentials private. In `/admin/`, the trusted superuser creates an
active staff account and assigns Owner, Reception or Counter. Owner is a business
role and does not grant Django User/Group administration. Do not mark every staff
account superuser. Roles are assigned to Django User, not the shared club Member.

`setup_staff_roles` is repeatable and additive. It creates the three Groups and
ensures their required permissions without replacing existing users, passwords,
group memberships or extra permissions. Administrators must review any extra
permissions on existing Groups; the command deliberately does not revoke them.

## Actual local integration

- Applied only already-published upstream `club.0005` to the verified existing
  development database `champions_club`, PostgreSQL16.16 at127.0.0.1:5433.
  No authentication/schema migration was invented. All26 migrations applied.
- Created the three role Groups and assigned the existing `utkarsh_counter`
  account Counter. Existing password, staff status and direct permissions were
  retained. No superuser or new persistent account was created.
- Existing business records remain21Products,6Members,3Plans,5Courts,8Sales,
  8SaleItems,0Bookings. Business row counts/hashes were verified unchanged.
  The existing account retains its password and flags; only intended group
  membership, normal last_login and temporary login sessions changed.
- Local server now runs this protected checkout with explicit DJANGO_DEBUG=True
  at http://127.0.0.1:8000/. Direct anonymous dashboard/member/export/receipt/
  pricing/counter URLs returned302 to staff login. Safe public pages/assets200.
- Existing encrypted credentials were used for a live browser login without
  printing/changing the password. Counter landing and21products verified;
  dashboard/member directory/export403, logout restored private-route302.
- All original worktrees/uncommitted files and PostgreSQL volume preserved.
  No persistent sales or bookings were created during browser verification.

## Executed verification

Python3.13.7 / Django5.2.19 / PostgreSQL16.16:

- **269 full-suite tests passed**, zero failures/errors/skips.
- **25 dedicated authentication tests passed**: anonymous/nonstaff/inactive/
  unassigned denials, Owner/Reception/Counter access, failed/successful login,
  password hashing/session, CSRF, logout, safe/external/ungranted redirects,
  receipts/exports/privateJSON, denied mutations/no stock changes, private-cache
  headers, public-data privacy and unknown routes (including static-like paths).
- **One Edge role/workflow audit passed** on disposable test database records:
  anonymous redirects, nonstaff rejection, all role boundaries, authenticated
  sale25.00 and stock10->8->10, sale receipt, logout, mobile390x844 with no overflow
  or JavaScript errors. Final login screenshot was visually inspected.
- **One persistent browser audit passed** with unchanged encrypted existing
  staff credentials; only session login/logout, no business transactions.
- System checks, migration consistency and whitespace checks passed.

The latest upstream added `club/tests.py` alongside the existing `club/tests/`
package, breaking default discovery. Preserved/moved its seven payment tests to
`club/tests/test_booking_payments.py`, so the full suite executes both sets.
Existing business request tests now use explicit authenticated staff fixtures;
the middleware is not disabled. Old anonymous-access tests were replaced with
denial checks. The first persistent Counter login uncovered an ungranted root
`next` destination; role-aware redirect was fixed and regression-tested.

```text
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py test frontend.tests.test_staff_authentication --verbosity 1 --noinput
python -B manage.py test --verbosity 1 --noinput
python -B <external staff-authentication/browser-audit.py>
python -B manage.py migrate club 0005 --noinput
python -B manage.py setup_staff_roles
python -B manage.py migrate --plan
git diff --check
```

## Jury explanation and remaining delivery

"Private club data requires a verified staff login. The server checks the
account's role on every request, so typing a URL cannot bypass permissions.
Owners, reception and counter staff have different access. Passwords are hashed,
sessions are server-side, and writes require CSRF tokens. Public visitors can
browse facilities without seeing member or transaction records."

This policy is implemented/tested locally and will be published for review; it
must be merged before other checkouts running main gain this protection. No
automatic merge or direct push to main. Production hosting, HTTPS/secret setup,
password recovery delivery and login rate limiting are not claimed as verified.
Development DEBUG must never be treated as a public production deployment.
