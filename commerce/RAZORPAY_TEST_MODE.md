# Actual Razorpay Test Mode — 2026-11-22

This is the official Razorpay Checkout integration for TEST payments, for both
shop/bar sales and court bookings. It uses `razorpay==2.0.1`, Razorpay Orders API,
`https://checkout.razorpay.com/v1/checkout.js` and server-side payment fetching.
Only `rzp_test_` keys are accepted. Live-mode payments are disabled.

**Current external verification blocker:** the user has no Razorpay test API keys.
No order or payment has been executed against Razorpay. PostgreSQL tests and
browser handoff tests use explicitly mocked provider responses; these results
are not evidence of an actual hosted checkout payment.

## Activate the hosted checkout

1. Create/sign in to a Razorpay account at https://dashboard.razorpay.com/.
2. Switch the dashboard to **Test Mode**, then generate API keys in its API Keys
   settings. Use the test key ID beginning `rzp_test_`, never a live key.
3. Configure the checkout's ignored local `.env`:

   ```dotenv
   RAZORPAY_TEST_MODE_ENABLED=True
   RAZORPAY_KEY_ID=your_rzp_test_key_id
   RAZORPAY_KEY_SECRET=your_test_secret
   ```

   Keep the secret out of chat, source control and frontend JavaScript. The key
   ID is public; the key secret stays server-side. This worktree's `.env` has
   the flag enabled with both keys blank, so it shows a setup message instead
   of claiming a successful payment.
4. Set automatic payment capture in Razorpay's Test Mode dashboard. The server
   accepts only a fetched **captured** payment. An authorized/failed payment is
   rejected without completing a sale or marking a booking paid.
5. Install project requirements, then run the existing migrations and restart
   Django. Local additive migrations are already applied, with 30 total:

   ```text
   python -m pip install -r requirements.txt
   python -B manage.py check
   python -B manage.py makemigrations --check --dry-run
   python -B manage.py migrate --plan
   python -B manage.py migrate --noinput
   python -B manage.py runserver 127.0.0.1:8000 --noreload
   ```

6. Create a new card/UPI guest or member sale, or reserve a paid card/UPI court
   slot. Select **Pay with Razorpay (Test)**, then **Continue to Razorpay (Test)**
   to create a server order. **Pay with Razorpay (Test)** opens the official
   hosted checkout. Use only the test payment details currently documented by
   Razorpay. Rehearse failure, dismissal, success, same-record retry and business
   cancellation. Verify provider capture in the Test Mode dashboard and saved
   provider IDs/stock locally before claiming the integration demo-ready.

Official documentation consulted:

- [Standard Checkout integration and test flow](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/)
- [Create Order API](https://razorpay.com/docs/api/orders/create/)
- [Fetch Payment API](https://razorpay.com/docs/api/payments/fetch-with-id/)

## Backend and frontend contract

| Named URL | Method | Path |
| --- | --- | --- |
| `commerce:razorpay_payment` | GET/HEAD | `/commerce/razorpay/<kind>/<pk>/` |
| `commerce:razorpay_order_create` | POST, CSRF | `/commerce/razorpay/<kind>/<pk>/order/` |
| `commerce:razorpay_payment_verify` | POST, CSRF | `/commerce/razorpay/<kind>/<pk>/verify/` |

`kind` is `sale` or `booking`. GET creates no provider order or payment.
The order POST accepts no caller amount: Decimal totals come from shared sale
quoting or the saved booking snapshot, converted exactly to integer paise.
Store the returned order ID/amount/method on the existing Sale or Booking.
Local retries reuse that order. If its amount or method changes, reject checkout
and create a new business transaction after cancelling the old one; do not
silently replace the order after someone may already have paid it.

Verification POST fields are `csrfmiddlewaretoken`, `razorpay_order_id`,
`razorpay_payment_id` and `razorpay_signature`. Verify the signature using the
**saved server order ID**, then fetch payment with server test credentials.
Require the exact order/payment IDs, amount, INR currency, stored card/UPI method,
captured status, `captured=True` and zero refunded amount before fulfillment.
Browser success, caller prices or a signature alone cannot complete the purchase.

Service functions:

- `create_test_order(kind, pk)` creates/reuses the saved provider order under
  a PostgreSQL parent lock, with bounded provider request timeouts.
- `verify_test_payment(kind=..., pk=..., order_id=..., payment_id=..., signature=...)`
  verifies capture, then calls existing atomic `complete_sale` or records payment
  on the existing confirmed Booking in the same database transaction.
- Same payment retry returns the existing record without a second stock deduction.
  Cancellation serializes on the same business row and retains provider references.
- A saved Razorpay order blocks local simulated-success and manual Sale completion
  paths until the server verifies its payment. Cash and non-provider legacy flows
  preserve existing behavior. Existing anonymous demo access is unchanged.

Template `frontend/templates/commerce/razorpay_payment.html` has context:
`target_kind`, `target_id`, `target_label`, `amount`, `payment_method_label`,
`return_url`, `payable`, `error_message`, `checkout_config`, `provider_reference`,
`payment_is_simulated`. `checkout_config` is serialized via `json_script` and
contains only public key, saved order, paise amount, currency, merchant/description,
method and named verification URL. It never contains the key secret.

Missing keys/provider outage return 503, disabled mode/missing target 404,
invalid form 400, mismatched signature/payment/stale amount/stock 409, missing
CSRF 403 and wrong HTTP methods 405. SDK load failure/dismissal/failure show retry
feedback without business mutation. Success POST redirects to existing detail.

## Limits and preservation

No independent Payment model, real-money mode, login layer or new frontend
framework. Razorpay test payments are marked `payment_is_simulated=True`, with
actual test `razorpay_payment_id` on receipts rather than a fabricated DEMO ID.
Existing local simulator remains available when Razorpay mode is disabled.

No webhook or automatic reconciliation/refund is implemented. If a test payment
is captured but the callback is lost or inventory/price has changed, the local
transaction stays unpaid/draft; inspect the Test Mode dashboard and retry the
same verification after resolving the issue. Do not submit another payment just
because local fulfillment failed. Cancellation releases stock/slot but sends no
refund request. This test-only limitation must be resolved before any live launch.
Stock is not reserved at order creation. A timed-out order-create request may
leave an unused remote order, but cannot create a successful local payment.

Additive migrations `commerce.0005` and `club.0007` add nullable Decimal order
amount, blank order ID, method and payment ID to existing records. No shared
Member/Plan duplication. Both applied to local PostgreSQL16.16 after backup:
`%TEMP%\champions-before-razorpay-test-20261122.dump`.
Original-column checksums preserved 21 products, 11 sales/items, 6 members,
3 plans, 5 courts, 4 bookings and 3 participants observed immediately before
migration. Original source branch, untracked files, worktrees and Docker volume
remain intact. Other teammates' changes require normal PR review before merge.

## Executed verification

Python3.13.7 / Django5.2.19 / PostgreSQL16.16:

- System and migration consistency checks passed.
- Full suite: **314 passed**, zero failures/errors/skips, including **32 new
  Razorpay tests** and three new provider-flow concurrency tests.
- Two Edge browser handoff audits passed with **mocked API and hosted SDK**,
  real HMAC/SDK signature verification and real PostgreSQL mutations. Covered
  missing-key503, order/create, failure/dismissal, verified callback, retries,
  sale cancellation stock10→8→10, booking payment/cancellation and mobile390px
  with no JavaScript/local asset errors.
- **Actual Razorpay order creation, hosted Test Mode payment and capture have
  not run because API keys are absent.**

External scripts/artifacts: `%TEMP%\champions-razorpay-browser-audit.py` and the
session visualizations `razorpay-test-handoff` directory. No browser dependencies
added to application requirements. The existing external verification Python
is documented in `POSTGRES_VERIFICATION.md`.

Tests exercise provider mode using per-test overrides. For the full suite set
`RAZORPAY_TEST_MODE_ENABLED=False` as the suite baseline (via runtime test settings
if the ignored `.env` enables the interactive demo); Razorpay test classes enable
their own mocked configuration. Existing simulator tests retain their contracts.
