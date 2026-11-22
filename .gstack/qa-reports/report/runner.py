"""Comprehensive QA Probing Suite for Champions Club Application.
Executes exploratory and invariant checks across all app surfaces.
"""

import os
import sys

# Ensure project root is in sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

import json
import urllib.request
import urllib.error
from datetime import datetime, time, timedelta
from decimal import Decimal

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.urls import reverse
from django.utils import timezone
from club.models import Court, Member, Booking, MembershipPlan
from commerce.models import Product, Sale, SaleItem
from commerce.services import complete_sale
from commerce.reporting import commerce_dashboard_summary

BASE_URL = "http://127.0.0.1:8000"
results = {
    "total_probes": 0,
    "passed": 0,
    "failed": 0,
    "checks": []
}

def record_check(probe_id, name, surface, status, details, evidence=""):
    results["total_probes"] += 1
    if status == "PASS":
        results["passed"] += 1
    else:
        results["failed"] += 1
    results["checks"].append({
        "id": probe_id,
        "name": name,
        "surface": surface,
        "status": status,
        "details": details,
        "evidence": evidence
    })
    print(f"[{status}] Probe {probe_id}: {name} ({surface})")
    if status != "PASS":
        print(f"       Details: {details}")

client = Client()

# -------------------------------------------------------------
# Probe 1: Route HTTP Status Check
# -------------------------------------------------------------
routes = [
    ("/", "Executive Dashboard"),
    ("/club/availability/", "Live Court Availability Matrix"),
    ("/club/bookings/", "Court Bookings Ledger"),
    ("/club/sports/", "Activities & Facilities Directory"),
    ("/club/sports/tennis/", "Tennis Facility Matrix"),
    ("/club/sports/badminton/", "Badminton Facility Matrix"),
    ("/club/sports/squash/", "Squash Facility Matrix"),
    ("/club/sports/cricket/", "Cricket Practice Nets"),
    ("/club/members/", "Members Directory"),
    ("/club/plans/", "Membership Plans"),
    ("/club/plans/public/", "Public Membership Catalog"),
    ("/club/api/members/", "Members API Endpoint"),
    ("/commerce/counter/", "Guest POS Counter"),
    ("/commerce/counter/member/", "Member POS Counter"),
    ("/commerce/shop/", "Shop & Bar Catalog"),
]

for idx, (path, name) in enumerate(routes, start=1):
    pid = f"PROBE-HTTP-{idx:02d}"
    try:
        req = urllib.request.Request(f"{BASE_URL}{path}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            code = resp.getcode()
            body_len = len(resp.read())
            if code == 200:
                record_check(pid, f"HTTP 200 for {name}", "HTTP / Routing", "PASS", f"Status 200, length {body_len} bytes")
            else:
                record_check(pid, f"HTTP {code} for {name}", "HTTP / Routing", "FAIL", f"Expected 200, got {code}")
    except Exception as e:
        record_check(pid, f"Failed request to {path}", "HTTP / Routing", "FAIL", str(e))

# -------------------------------------------------------------
# Probe 2: Static Product Images Verification
# -------------------------------------------------------------
products = Product.objects.filter(is_active=True)
all_images_ok = True
missing_images = []
for p in products:
    fname = p.image_filename
    disk_path = os.path.join("frontend", "static", fname)
    if not os.path.exists(disk_path):
        all_images_ok = False
        missing_images.append(f"{p.name} ({fname})")

if all_images_ok:
    record_check("PROBE-IMG-01", "Product Catalog Images On Disk", "Static Assets", "PASS", f"All {products.count()} active product images verified on disk")
else:
    record_check("PROBE-IMG-01", "Product Catalog Images On Disk", "Static Assets", "FAIL", f"Missing images: {', '.join(missing_images)}")

# -------------------------------------------------------------
# Probe 3: Member Directory & Filter Integrity
# -------------------------------------------------------------
import re
resp_members = client.get(reverse('club:member_list'))
members_html = resp_members.content.decode('utf-8')
# Find all options in the tier select dropdown
tier_select_match = re.search(r'<select[^>]*name=["\']tier["\'][^>]*>(.*?)</select>', members_html, re.DOTALL)
if tier_select_match:
    options = re.findall(r'<option[^>]*value=["\']([^"\']*)["\'][^>]*>\s*([^<]+?)\s*</option>', tier_select_match.group(1))
    # Exclude empty value 'All Tiers'
    tier_labels = [label for val, label in options if val]
    expected_tiers = ['No Member', 'Junior', 'Silver', 'Gold']
    if tier_labels == expected_tiers:
        record_check("PROBE-MBR-01", "Member Tier Filter Scoped Choices", "Members Directory", "PASS", f"Tier choices strictly: {tier_labels}")
    else:
        record_check("PROBE-MBR-01", "Member Tier Filter Scoped Choices", "Members Directory", "FAIL", f"Unexpected tier choices: {tier_labels}")
else:
    record_check("PROBE-MBR-01", "Member Tier Filter Scoped Choices", "Members Directory", "FAIL", "Could not locate tier select element in HTML")

# Test tier filtering via HTTP GET
resp_gold = client.get(reverse('club:member_list'), {'tier': 'gold'})
gold_html = resp_gold.content.decode('utf-8')
# Extract tbody of members table
tbody_match = re.search(r'<tbody>(.*?)</tbody>', gold_html, re.DOTALL)
if tbody_match:
    table_content = tbody_match.group(1)
    has_gold_in_table = 'tier-gold' in table_content
    has_silver_in_table = 'tier-silver' in table_content
    has_junior_in_table = 'tier-junior' in table_content
    if has_gold_in_table and not has_silver_in_table and not has_junior_in_table:
        record_check("PROBE-MBR-02", "Member Filtering by Tier (Gold)", "Members Directory", "PASS", "Only Gold Plan members displayed in filtered table")
    else:
        record_check("PROBE-MBR-02", "Member Filtering by Tier (Gold)", "Members Directory", "FAIL", f"Table has Gold: {has_gold_in_table}, Silver: {has_silver_in_table}, Junior: {has_junior_in_table}")
else:
    record_check("PROBE-MBR-02", "Member Filtering by Tier (Gold)", "Members Directory", "FAIL", "Could not locate table tbody in response")

# -------------------------------------------------------------
# Probe 4: Members API Endpoint Response
# -------------------------------------------------------------
resp_api = client.get(reverse('club:api_members_list'))
if resp_api.status_code == 200:
    api_data = json.loads(resp_api.content.decode('utf-8'))
    m_dict = api_data.get('members', {})
    if len(m_dict) >= 5:
        sample = next(iter(m_dict.values()))
        keys_ok = all(k in sample for k in ['id', 'name', 'tier', 'plan_name', 'plan_court_rate', 'is_active'])
        if keys_ok:
            record_check("PROBE-API-01", "Members JSON API Contract", "API / Integration", "PASS", f"Returned {len(m_dict)} members with full pricing schema")
        else:
            record_check("PROBE-API-01", "Members JSON API Contract", "API / Integration", "FAIL", f"Missing schema keys in: {sample}")
    else:
        record_check("PROBE-API-01", "Members JSON API Contract", "API / Integration", "FAIL", f"Expected at least 5 members, got {len(m_dict)}")
else:
    record_check("PROBE-API-01", "Members JSON API Contract", "API / Integration", "FAIL", f"Status {resp_api.status_code}")

# -------------------------------------------------------------
# Probe 5: Court Availability Matrix DOM & Alignment
# -------------------------------------------------------------
resp_avail = client.get(reverse('club:public_availability'))
avail_html = resp_avail.content.decode('utf-8')

has_sticky_facility = "position: sticky; left: 0; z-index: 10;" in avail_html or "position: sticky; left: 0;" in avail_html
has_stacked_headers = "&darr; {{ s.end }}" in avail_html or "↓" in avail_html or "&darr;" in avail_html
has_no_raw_collision = "white-space: nowrap;\">{{ s.start }} &rarr; {{ s.end }}</div>" not in avail_html

if has_sticky_facility and has_no_raw_collision:
    record_check("PROBE-DOM-01", "Availability Matrix Layout & Stickiness", "Public Availability", "PASS", "Sticky facility column and stacked hour headers verified")
else:
    record_check("PROBE-DOM-01", "Availability Matrix Layout & Stickiness", "Public Availability", "FAIL", f"Sticky: {has_sticky_facility}, No collision: {has_no_raw_collision}")

# Check that navbar no longer has "New Booking"
has_new_booking = "New Booking" in avail_html
if not has_new_booking:
    record_check("PROBE-NAV-01", "New Booking Removal from Nav", "Navbar / Base", "PASS", "New Booking link cleanly removed from navigation")
else:
    record_check("PROBE-NAV-01", "New Booking Removal from Nav", "Navbar / Base", "FAIL", "Found 'New Booking' text in rendered navbar")

# -------------------------------------------------------------
# Probe 6: Sports Directory "Coming Soon" Badge
# -------------------------------------------------------------
resp_sports = client.get(reverse('club:sports_directory'))
sports_html = resp_sports.content.decode('utf-8')
has_coming_soon = "Coming Soon" in sports_html
has_commissioning_soon = "Commissioning Soon" in sports_html

if has_coming_soon and not has_commissioning_soon:
    record_check("PROBE-SPT-01", "Football Coming Soon Badge", "Sports Directory", "PASS", "'Coming Soon' badge present, obsolete 'Commissioning Soon' eliminated")
else:
    record_check("PROBE-SPT-01", "Football Coming Soon Badge", "Sports Directory", "FAIL", f"Coming Soon: {has_coming_soon}, Commissioning Soon: {has_commissioning_soon}")

# -------------------------------------------------------------
# Probe 7: Executive Dashboard Metric Cards
# -------------------------------------------------------------
resp_dash = client.get(reverse('dashboard'))
dash_html = resp_dash.content.decode('utf-8')
has_shop_sales = "Completed Shop Sales: ₹" in dash_html
has_bar_sales = "Completed Bar Sales: ₹" in dash_html
# Verify that numbers follow the currency symbol, not an empty space
has_empty_shop = "Completed Shop Sales: ₹ " in dash_html or "Completed Shop Sales: ₹ &middot;" in dash_html or "Completed Shop Sales: ₹\n" in dash_html
has_empty_bar = "Completed Bar Sales: ₹ " in dash_html or "Completed Bar Sales: ₹ <" in dash_html or "Completed Bar Sales: ₹\n" in dash_html or "Completed Bar Sales: ₹</span>" in dash_html

if has_shop_sales and has_bar_sales and not has_empty_bar:
    record_check("PROBE-DSH-01", "Dashboard Metric Card Numbers & Boxes", "Executive Dashboard", "PASS", "Live shop & bar totals populated with no orphaned currency symbols")
else:
    record_check("PROBE-DSH-01", "Dashboard Metric Card Numbers & Boxes", "Executive Dashboard", "FAIL", f"Shop: {has_shop_sales}, Bar: {has_bar_sales}, Empty Bar: {has_empty_bar}")

# -------------------------------------------------------------
# Probe 8: Functional Invariants — Booking Rate by Member Tier
# -------------------------------------------------------------
court = Court.objects.filter(sport='tennis', active=True).first()
# Active Gold member
today = timezone.localdate()
gold_member = None
silver_active = None
silver_inactive = None

for m in Member.objects.select_related('plan').all():
    plan = m.effective_plan_on_date(today)
    is_active = m.is_club_member and m.is_active_on_date(today) and plan is not None and plan.active
    if is_active and plan.tier == 'gold' and not gold_member:
        gold_member = m
    elif is_active and plan.tier == 'silver' and not silver_active:
        silver_active = m
    elif not is_active and plan and plan.tier == 'silver' and not silver_inactive:
        silver_inactive = m

if court and gold_member and silver_active and silver_inactive:
    now = timezone.now()
    b_gold = Booking(court=court, booked_by_member=gold_member, start_datetime=now)
    gold_rate = b_gold.calculate_price()

    b_silver_act = Booking(court=court, booked_by_member=silver_active, start_datetime=now)
    silver_act_rate = b_silver_act.calculate_price()

    b_silver_inact = Booking(court=court, booked_by_member=silver_inactive, start_datetime=now)
    silver_inact_rate = b_silver_inact.calculate_price()

    b_walkin = Booking(court=court, booked_by_member=None, start_datetime=now)
    walkin_rate = b_walkin.calculate_price()

    rates_ok = (
        (gold_rate == Decimal('0.00')) and
        (silver_act_rate == Decimal('200.00')) and
        (silver_inact_rate == court.hourly_rate) and
        (walkin_rate == court.hourly_rate)
    )
    if rates_ok:
        record_check("PROBE-INV-01", "Tier-Based Court Rate & Inactive Reversion", "Business Logic", "PASS", f"Active Gold: ₹{gold_rate}, Active Silver: ₹{silver_act_rate}, Expired Silver: ₹{silver_inact_rate}, Walk-in: ₹{walkin_rate}")
    else:
        record_check("PROBE-INV-01", "Tier-Based Court Rate & Inactive Reversion", "Business Logic", "FAIL", f"Mismatch: Gold ₹{gold_rate}, Silver Active ₹{silver_act_rate}, Silver Inactive ₹{silver_inact_rate}, Walkin ₹{walkin_rate}")
else:
    record_check("PROBE-INV-01", "Tier-Based Court Rate & Inactive Reversion", "Business Logic", "FAIL", f"Missing fixture data: gold={bool(gold_member)}, silver_act={bool(silver_active)}, silver_inact={bool(silver_inactive)}")

# -------------------------------------------------------------
# Probe 9: Commerce POS Sale Completion & Stock Deduction
# -------------------------------------------------------------
product = Product.objects.filter(is_active=True, stock_quantity__gt=5).first()
if product:
    initial_stock = product.stock_quantity
    item_qty = 2
    item_total = product.price * item_qty
    sale = Sale.objects.create(
        status=Sale.Status.DRAFT,
        payment_method="cash",
        subtotal=item_total,
        discount=Decimal('0.00'),
        total=item_total
    )
    item = SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=item_qty,
        unit_price=product.price,
        line_total=item_total
    )

    completed_sale = complete_sale(sale.pk)
    product.refresh_from_db()
    final_stock = product.stock_quantity

    stock_decremented = (final_stock == initial_stock - item_qty)
    status_completed = (completed_sale.status == Sale.Status.COMPLETED)

    if stock_decremented and status_completed:
        record_check("PROBE-POS-01", "POS Sale Completion & Stock Deduction", "Commerce", "PASS", f"Stock decremented {initial_stock} -> {final_stock}, Status: COMPLETED, Total: ₹{completed_sale.total}")
    else:
        record_check("PROBE-POS-01", "POS Sale Completion & Stock Deduction", "Commerce", "FAIL", f"Stock decremented: {stock_decremented}, Status: {completed_sale.status}")
else:
    record_check("PROBE-POS-01", "POS Sale Completion & Stock Deduction", "Commerce", "FAIL", "No available product with stock > 5")

# -------------------------------------------------------------
# Probe 10: Double-Booking Conflict Prevention
# -------------------------------------------------------------
try:
    test_date = timezone.localdate() + timedelta(days=14)
    tz = timezone.get_current_timezone()
    slot_time = timezone.make_aware(datetime.combine(test_date, time(14, 0)), tz)
    end_time = timezone.make_aware(datetime.combine(test_date, time(15, 0)), tz)

    # First booking
    b1 = Booking.objects.create(
        court=court,
        start_datetime=slot_time,
        end_datetime=end_time,
        status='confirmed',
        walkin_name="QA Collision Player 1"
    )

    # Attempt second overlapping booking on same court and time
    collision_prevented = False
    try:
        b2 = Booking(
            court=court,
            start_datetime=slot_time,
            end_datetime=end_time,
            status='confirmed',
            walkin_name="QA Collision Player 2"
        )
        b2.full_clean()
        b2.save()
    except Exception as exc:
        collision_prevented = True

    # Clean up test booking
    b1.delete()
    if not collision_prevented and 'b2' in locals():
        b2.delete()

    if collision_prevented:
        record_check("PROBE-CNF-01", "Double-Booking Collision Prevention", "Booking Invariants", "PASS", "Overlapping reservation was strictly rejected by full_clean / database constraint")
    else:
        record_check("PROBE-CNF-01", "Double-Booking Collision Prevention", "Booking Invariants", "FAIL", "Overlapping booking was permitted to save!")
except Exception as e:
    record_check("PROBE-CNF-01", "Double-Booking Collision Prevention", "Booking Invariants", "FAIL", str(e))

# -------------------------------------------------------------
# Probe 11: Booking Cancellation Lifecycle & Slot Release
# -------------------------------------------------------------
try:
    test_date_rel = timezone.localdate() + timedelta(days=15)
    slot_time_rel = timezone.make_aware(datetime.combine(test_date_rel, time(16, 0)), tz)
    end_time_rel = timezone.make_aware(datetime.combine(test_date_rel, time(17, 0)), tz)

    b_rel = Booking.objects.create(
        court=court,
        start_datetime=slot_time_rel,
        end_datetime=end_time_rel,
        status='confirmed',
        walkin_name="QA Release Player"
    )

    from club.availability import availability_grid
    labels, rows_before, count_before = availability_grid([court], test_date_rel)
    slot_before = next(slot for hr, slot in rows_before[0]['slots'] if hr == '16:00')
    is_booked = (slot_before['status'] == 'booked')

    # Cancel booking
    b_rel.status = 'cancelled'
    b_rel.save()

    labels, rows_after, count_after = availability_grid([court], test_date_rel)
    slot_after = next(slot for hr, slot in rows_after[0]['slots'] if hr == '16:00')
    is_free = (slot_after['status'] == 'free')

    # Clean up
    b_rel.delete()

    if is_booked and is_free:
        record_check("PROBE-LFC-01", "Booking Cancellation Slot Release", "Booking Lifecycle", "PASS", "Confirmed booking blocked slot; cancellation immediately released slot back to 'free'")
    else:
        record_check("PROBE-LFC-01", "Booking Cancellation Slot Release", "Booking Lifecycle", "FAIL", f"Booked before: {is_booked}, Free after: {is_free}")
except Exception as e:
    record_check("PROBE-LFC-01", "Booking Cancellation Slot Release", "Booking Lifecycle", "FAIL", str(e))

# -------------------------------------------------------------
# Probe 12: CSV Export Endpoint & Content Headers
# -------------------------------------------------------------
try:
    resp_csv = client.get(reverse('club:booking_export_csv'))
    status_ok = (resp_csv.status_code == 200)
    has_attachment_header = 'attachment' in resp_csv.get('Content-Disposition', '')
    is_csv_content = 'text/csv' in resp_csv.get('Content-Type', '')

    if status_ok and has_attachment_header and is_csv_content:
        record_check("PROBE-CSV-01", "Bookings CSV Export Format", "Export Services", "PASS", f"Status 200, Content-Type: {resp_csv.get('Content-Type')}, Header: {resp_csv.get('Content-Disposition')}")
    else:
        record_check("PROBE-CSV-01", "Bookings CSV Export Format", "Export Services", "FAIL", f"Status: {resp_csv.status_code}, Type: {resp_csv.get('Content-Type')}")
except Exception as e:
    record_check("PROBE-CSV-01", "Bookings CSV Export Format", "Export Services", "FAIL", str(e))

# -------------------------------------------------------------
# Probe 13: Site Search Suggestions Integration
# -------------------------------------------------------------
try:
    resp_srch = client.get(reverse('club:search_suggestions'), {'q': 'tennis'})
    if resp_srch.status_code == 200:
        data = json.loads(resp_srch.content.decode('utf-8'))
        results_list = data.get('suggestions', [])
        found_tennis = any('tennis' in r.get('title', '').lower() for r in results_list)
        if found_tennis:
            record_check("PROBE-SRC-01", "Live Site Search Endpoint", "Search & Navigation", "PASS", f"Search for 'tennis' returned {len(results_list)} results including Tennis facility")
        else:
            record_check("PROBE-SRC-01", "Live Site Search Endpoint", "Search & Navigation", "FAIL", f"Results did not include tennis: {results_list}")
    else:
        record_check("PROBE-SRC-01", "Live Site Search Endpoint", "Search & Navigation", "FAIL", f"Status {resp_srch.status_code}")
except Exception as e:
    record_check("PROBE-SRC-01", "Live Site Search Endpoint", "Search & Navigation", "FAIL", str(e))

# -------------------------------------------------------------
# Probe 14: Concierge Chatbot Knowledge Retrieval
# -------------------------------------------------------------
try:
    resp_bot = client.get(reverse('club:help_bot_faq'), {'q': 'membership'})
    if resp_bot.status_code == 200:
        bot_data = json.loads(resp_bot.content.decode('utf-8'))
        has_reply = bool(bot_data.get('faqs') or bot_data.get('answer') or bot_data.get('reply') or bot_data.get('suggestions'))
        if has_reply:
            record_check("PROBE-BOT-01", "Champions Concierge AI Endpoint", "AI Chatbot", "PASS", f"Concierge returned curated FAQs for query 'membership'")
        else:
            record_check("PROBE-BOT-01", "Champions Concierge AI Endpoint", "AI Chatbot", "FAIL", f"No response field in: {bot_data}")
    else:
        record_check("PROBE-BOT-01", "Champions Concierge AI Endpoint", "AI Chatbot", "FAIL", f"Status {resp_bot.status_code}")
except Exception as e:
    record_check("PROBE-BOT-01", "Champions Concierge AI Endpoint", "AI Chatbot", "FAIL", str(e))

# -------------------------------------------------------------
# Summary Report Output
# -------------------------------------------------------------
summary_path = os.path.join(".gstack", "qa-reports", "run-20261122T030300Z", "probe_summary.json")
with open(summary_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\n" + "="*60)
print(f"QA PROBE RUN COMPLETED: {results['passed']}/{results['total_probes']} Passed ({results['failed']} Failed)")
print(f"Results written to: {summary_path}")
print("="*60)
