# Champions Club - shared build contract

This contract is technology-neutral. It defines the information and feature handoffs the team must share; it does not require Odoo or prescribe a programming language, framework, database, or hosting provider. Adapt names to the chosen stack, but keep the relationships and meanings consistent.

## Shared data contract

| Concept | Shared record and key fields | Owner |
|---|---|---|
| Membership plan | `MembershipPlan`: `id`, tier (`gold`, `silver`, `junior`), membership price if applicable, court pricing/entitlement, shop discount, bar discount, active status | Nayan |
| Member | `Member`: `id`, name, contact details, `plan_id` (or tier linked to a plan), membership start/end dates; derive active/expired state from dates and any explicit suspension status | Nayan |
| Court | `Court`: `id`, name, sport (`tennis`, `cricket`, etc.), capacity, active status | Nayan |
| Booking | `Booking`: `id`, optional `booked_by_member_id` for walk-ins, `court_id`, start/end time, status (`draft`, `confirmed`, `cancelled`), type (`standard`, `social`), price, currency; link players through `BookingParticipant` records (member ID optional for guest participants) | Nayan |
| Product | `Product`: `id`, name, category (`shop` or `bar`), price, stock quantity, low-stock threshold, active status | Pratik |
| Sale | `Sale` and `SaleItem`: `id`, optional `member_id`, date/time, status (`draft`, `completed`, `cancelled`, `refunded` as supported), subtotal, discount, tax if in scope, total; each item links a product, quantity, unit-price snapshot, discount, and line total | Pratik |
| Payment | `Payment`: `id`, amount, method (`cash`, `card`, `UPI`, etc.), status, paid time, and a link to one booking or sale; allow multiple payments only if tabs/partial payments are in scope | Parth (integration) |
| Enquiry | `Enquiry`: `id`, visitor name/contact, message or trial request, status, created time; link to a member if converted | Utkarsh |
| Owner summary | A read-only view computed from bookings and sales for a chosen date range; no separately typed totals | Utkarsh |

Use one member record everywhere. A booking and a sale should refer to the same member ID; do not create separate member/customer lists. Use one product and stock source for counter and online orders. Store the booking price and sale item price/discount at confirmation so later plan or price changes do not rewrite history. Store timestamps consistently (prefer UTC) and convert to the club's configured local timezone when enforcing daily rules and displaying schedules. Membership active/expired state should not be a separately editable flag that can contradict its dates.

## MVP business rules

- Sessions last 60 minutes; start times are available every 30 minutes.
- A confirmed booking cannot overlap another confirmed booking for the same court. Cancelled bookings release the slot.
- A member can play in at most two confirmed bookings per local club date. Count a member's participation, including social-play bookings, once per booking; guest participants without member records do not count toward a member's limit.
- Member and walk-in prices can differ. Apply membership tier discounts to shop/bar sales where practical.
- Social play is one court booking with multiple participants; it still blocks that court for the full time.
- Track product stock through both counter and online orders. Do not decrement stock twice for one sale.
- The owner summary reads actual booking, payment, and completed sale records; confirmed booking value is not automatically the same as money collected. Show booked/earned value separately from collected payments unless the app records payment status and amounts. Exclude cancelled/voided activity and label any revenue sources it does not include.
- Prevent overlapping bookings at the authoritative server/database layer, not only by hiding unavailable slots in the screen, so simultaneous requests cannot double-book a court.

## Role roadmaps

Build the smallest working slice first. Keep the shared data contract stable; discuss any change with Parth and update this file before others depend on it.

### Parth - Product lead and integration owner

**Goal:** make one shared project run, connect each feature through the agreed records, and protect a repeatable demo.

1. Record the chosen language/framework, database, hosting/run method, and judging rubric so every teammate uses the same setup.
2. Create or verify the shared project structure, environment configuration example, start instructions, and one shared integration branch/repository.
3. Establish the shared database schema or API contract for Member, Court, Booking, Product, Sale, SaleItem, and Enquiry. Keep the first pass minimal.
4. Add the app shell: navigation, common layout, error handling, and any basic access rules needed for the demo. Avoid implementing teammates' feature screens unless unblocking them.
5. Integrate small working changes frequently. Coordinate edits to shared schema, API shapes, routes, and navigation.
6. Prepare seeded demo data and a repeatable reset/restart path. Run the full member-to-booking-to-sale-to-owner-summary story.
7. Rehearse the final pitch and keep the last hours for stabilization.

**Done when:** a teammate can start the app using the shared instructions; the shared records persist; the complete demo path works on seeded data without manual database edits.

**Handoff:** share the run steps, schema/API changes, demo account/data, and the stable path to demonstrate.

### Nayan - Membership and court operations

**Goal:** let front-desk staff identify members and book courts with clear prices and no conflicts.

1. Implement member creation/editing with tier and membership dates using the agreed `Member` shape.
2. Implement court creation/listing using `Court`.
3. Implement booking creation/listing using `Booking`, linked to the agreed member and court IDs.
4. First make the basic flow work: select member or walk-in, select court and start time, calculate one-hour end time, show price, confirm booking.
5. Add 30-minute start increments, same-court overlap prevention, and the two-confirmed-bookings-per-member-per-local-day limit. Cancelled bookings must not block a slot.
6. Store the confirmed price on the booking. Add tier and walk-in pricing. Add social play only after standard booking works.
7. Connect the feature to the shared project and give Parth a member/court/booking example.

**Done when:** staff can create a member and court, make a valid booking, see the correct price, and get a clear error for an overlap or daily-limit violation.

**Handoff:** document the booking status values and which records count in reporting; tell Utkarsh the exact date, price, and member fields to read.

### Pratik - Shop and bar sales

**Goal:** record shop/bar sales against one product stock source and apply member discounts.

1. Implement a small, believable set of products using the agreed `Product` shape, including shop and bar categories.
2. Build the basic sale flow for a walk-in and a member, using the same member IDs Nayan created.
3. Record each sale and its line items using `Sale` and `SaleItem`; compute subtotal, discount, and total consistently.
4. Update stock exactly once when a sale completes; handle cancelled/voided sales consistently.
5. Apply tier discounts if time allows. If automatic discounting is too costly, provide a clear explicit discount action and tell Parth the limitation.
6. Add online order, pickup/delivery, bar tabs, or shifts only after the basic sale and stock update work.
7. Give Parth and Utkarsh a sample sale and the fields/statuses for reporting.

**Done when:** the same member can be selected on a sale, the total/discount is visible, product stock changes once, and the sale can be read in the owner summary.

**Handoff:** specify the sale statuses, payment method values, and category field used to separate shop from bar.

### Utkarsh - Owner visibility and online entry point

**Goal:** show the owner activity across bookings and sales, and help visitors contact the club.

1. Confirm the agreed Booking, Sale, and SaleItem shapes with Nayan and Pratik; do not create shadow totals.
2. Build the owner view first: date range, confirmed court bookings/revenue, completed shop/bar sales, and simple source breakdown.
3. Compute the summary from source records. Exclude cancelled bookings and voided sales; make the selected range and included sources clear.
4. Add a minimal public club page with plans/prices and a trial/enquiry form only after reporting works.
5. Store enquiries in the agreed `Enquiry` shape. If a visitor becomes a member, link the enquiry to that same member record.
6. Verify the summary changes after a booking is cancelled or a sale is added. Coordinate seeded data with Parth.

**Done when:** the owner can see booking and sales activity from real records; a visitor enquiry can be captured if the website stretch is completed.

**Handoff:** state aggregation rules, included sources, and reporting limitations. Do not label partial sources as total club revenue.

## First integration checkpoint

1. Start the app using Parth's shared instructions.
2. Create a member and court, then confirm a booking linked to both.
3. Try an overlapping booking; confirm it is rejected. Cancel the first booking and confirm the time becomes available.
4. Record a sale for that same member and confirm stock changes once.
5. Open the owner summary and confirm it reads the booking and sale records.

If the team chose a stack where a person is responsible for both frontend and backend, preserve these data meanings and relationships even if the implementation structure differs.
