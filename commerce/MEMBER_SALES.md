# Member counter sales

Sale.member references the existing club.Member with PROTECT; migration
0003_sale_member depends on club.0002_initial and commerce.0002_guest_sales.
Guest records remain nullable and old guest routes/forms retain their contract.

## Completion policy

- Discounts are read from the locked current MembershipPlan at completion.
- Member must be is_club_member, not suspended, active on timezone.localdate()
  under Member.is_active_on_date(), with an active plan.
- Nayan's null start/end dates mean open-ended membership boundaries.
- Expired/future/suspended/nonclub profiles or absent/inactive plans receive no
  discount but retain their Sale.member relationship.
- Shop uses shop_discount_percent; bar uses bar_discount_percent. No hardcoded
  tier rates. Values must be finite Decimal percentages 0..100 with two-decimal
  precision; invalid applied values fail safely before stock changes.
- Round each line subtotal's percentage discount once to paise using
  Decimal ROUND_HALF_UP. Sum the rounded line discounts and totals.
- Same completed Sale retry returns before reading changed membership/plan
  values. Historical item price/discount/total and Sale totals stay unchanged.
- Cancellation restores only original quantities, at most once.

Lock order: Sale, Member, MembershipPlan, items, then Product IDs in ascending
order. Nullable member/plan relations are locked with separate queries.
No shared model/settings changes or alternate customer/payment model added.

## Interface

create_sale(quantities={product_id: quantity}, payment_method="cash", member_id=pk)
creates a draft. create_guest_sale delegates to the same function with no member.

| Name | Method | Path |
| --- | --- | --- |
| commerce:member_counter | GET/HEAD, staff | /commerce/counter/member/ |
| commerce:member_sale_create | POST, staff/CSRF | /commerce/sales/member/create/ |

MemberSaleForm extends GuestSaleForm with required member (existing Member ID).
All member profiles may be selected; eligibility is checked at completion.
The other fields remain product, quantity and payment_method. No input price,
discount, stock or membership status is trusted.

Pratik's current frontend/commerce template adds Member sale entry/navigation,
the form's actual member selector and saved member identity. Existing guest
actions still work. Context adds member_mode; saved member details are current
profile attributes, not a customer-name snapshot.

Invalid submissions return HTTP400 with bound errors. Invalid applied plan
discount/state or insufficient stock at completion returns HTTP409; stock and
snapshots roll back. CSRF/auth/method protections and named success redirects
match guest routes. Duplicate draft creation is still not request-idempotent.

## Reporting handoff

Pratik owns dashboard changes. Use completed Sale/SaleItem records and saved
line amounts; exclude cancelled/draft records. Shared member ID is now available.
Confirmed booking value must not be labelled collected revenue. Product category
is currently mutable/current; agree category-history policy before aggregating
shop/bar history over product category changes.

## Publication

This member slice is dependent on Product -> guest backend -> new frontend.
It does not overwrite Nayan models, shared settings or the latest upstream
presentation cleanup. See DELIVERY.md for executed tests and PR links.
