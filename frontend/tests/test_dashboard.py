"""Owner summaries must reflect actual saved sales, booking values and stock."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import skipUnless

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from club.models import Booking, Court, Member, MemberPlanChange, MembershipPlan
from commerce.models import Product, Sale
from commerce.reporting import commerce_dashboard_summary
from commerce.services import cancel_sale, complete_sale, create_guest_sale, create_sale
from frontend.tests.helpers import login_test_staff


@skipUnless(connection.vendor == "postgresql", "Requires actual shared PostgreSQL records")
class OwnerDashboardTests(TestCase):
    def setUp(self):
        super().setUp()
        login_test_staff(self.client)

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.shop = Product.objects.create(
            name="Dashboard racket", category="shop", price=Decimal("12.50"),
            stock_quantity=20, low_stock_threshold=2,
        )
        cls.bar = Product.objects.create(
            name="Dashboard refreshment", category="bar", price=Decimal("2.00"),
            stock_quantity=20, low_stock_threshold=2,
        )

    def guest_sale(self, quantities=None):
        return create_guest_sale(
            quantities=quantities or {self.shop.pk: 2}, payment_method="cash",
        )

    def test_empty_totals_are_decimal_zero_and_trend_has_seven_dates(self):
        summary = commerce_dashboard_summary(today=self.today)
        for key in ["completed_sales_total", "shop_sales_total", "bar_sales_total"]:
            self.assertEqual(summary[key], Decimal("0.00"))
            self.assertIsInstance(summary[key], Decimal)
        self.assertEqual(summary["completed_sales_count"], 0)
        self.assertEqual(len(summary["sales_creation_trend"]), 7)
        self.assertEqual(summary["sales_creation_trend"][-1]["date"], self.today)

    def test_mixed_sale_is_counted_once_and_categories_use_saved_line_amounts(self):
        sale = complete_sale(self.guest_sale({self.shop.pk: 2, self.bar.pk: 2}).pk)
        complete_sale(sale.pk)
        Product.objects.filter(pk=self.shop.pk).update(price=Decimal("99.00"))
        Product.objects.filter(pk=self.bar.pk).update(price=Decimal("55.00"))
        summary = commerce_dashboard_summary()
        self.assertEqual(summary["completed_sales_total"], Decimal("29.00"))
        self.assertEqual(summary["shop_sales_total"], Decimal("25.00"))
        self.assertEqual(summary["bar_sales_total"], Decimal("4.00"))
        self.assertEqual(summary["completed_sales_count"], 1)
        self.assertEqual(summary["shop_sales_count"], 1)
        self.assertEqual(summary["bar_sales_count"], 1)

    def test_drafts_and_cancellations_are_excluded_from_totals_and_activity(self):
        self.guest_sale()
        sale = complete_sale(self.guest_sale().pk)
        cancel_sale(sale.pk)
        summary = commerce_dashboard_summary()
        self.assertEqual(summary["completed_sales_total"], Decimal("0.00"))
        self.assertEqual(summary["completed_sales_count"], 0)
        self.assertEqual(list(summary["recent_completed_sales"]), [])
        self.assertTrue(all(point["total"] == Decimal("0.00") for point in summary["sales_creation_trend"]))

    def test_member_discounts_are_reported_after_line_snapshots_not_current_plan(self):
        plan = MembershipPlan.objects.create(
            tier="silver", name="Silver", shop_discount_percent=Decimal("10.00"),
            bar_discount_percent=Decimal("5.00"),
        )
        member = Member.objects.create(name="Reporting member", plan=plan)
        sale = complete_sale(create_sale(
            quantities={self.shop.pk: 2, self.bar.pk: 2}, payment_method="UPI",
            member_id=member.pk,
        ).pk)
        MembershipPlan.objects.filter(pk=plan.pk).update(shop_discount_percent=Decimal("90.00"))
        summary = commerce_dashboard_summary()
        self.assertEqual(summary["shop_sales_total"], Decimal("22.50"))
        self.assertEqual(summary["bar_sales_total"], Decimal("3.80"))
        self.assertEqual(summary["completed_sales_total"], Decimal("26.30"))
        self.assertEqual(summary["completed_sales_total"], sale.total)

    def test_low_stock_alerts_use_active_products_and_boundary_threshold(self):
        low = Product.objects.create(
            name="Boundary low item", category="shop", price=Decimal("1.00"),
            stock_quantity=3, low_stock_threshold=3,
        )
        Product.objects.create(
            name="Inactive exhausted item", category="bar", price=Decimal("1.00"),
            stock_quantity=0, low_stock_threshold=5, is_active=False,
        )
        summary = commerce_dashboard_summary()
        self.assertEqual(summary["inventory_alert_count"], 1)
        self.assertEqual(list(summary["inventory_alerts"]), [low])

    def test_checkout_and_cancellation_update_alerts_and_revenue_immediately(self):
        Product.objects.filter(pk=self.shop.pk).update(stock_quantity=4, low_stock_threshold=2)
        sale = complete_sale(self.guest_sale().pk)
        summary = commerce_dashboard_summary()
        self.assertEqual(summary["inventory_alert_count"], 1)
        self.assertEqual(summary["completed_sales_total"], Decimal("25.00"))
        cancel_sale(sale.pk)
        summary = commerce_dashboard_summary()
        self.assertEqual(summary["inventory_alert_count"], 0)
        self.assertEqual(summary["completed_sales_total"], Decimal("0.00"))

    def test_sales_creation_dates_use_club_timezone_and_exclude_tomorrow(self):
        today_sale = complete_sale(self.guest_sale().pk)
        yesterday_sale = complete_sale(self.guest_sale().pk)
        future_sale = complete_sale(self.guest_sale().pk)
        tz = timezone.get_current_timezone()
        boundary = timezone.make_aware(datetime.combine(self.today, time.min), tz)
        Sale.objects.filter(pk=today_sale.pk).update(created_at=boundary)
        Sale.objects.filter(pk=yesterday_sale.pk).update(created_at=boundary - timedelta(seconds=1))
        Sale.objects.filter(pk=future_sale.pk).update(created_at=boundary + timedelta(days=1))
        summary = commerce_dashboard_summary(today=self.today)
        self.assertEqual(summary["sales_created_today_total"], Decimal("25.00"))
        self.assertEqual(summary["sales_created_today_count"], 1)
        self.assertEqual(summary["sales_creation_trend"][-2]["total"], Decimal("25.00"))
        self.assertEqual(summary["completed_sales_total"], Decimal("75.00"))

    def test_dashboard_separates_confirmed_booking_value_and_completed_sales(self):
        court = Court.objects.create(name="Reporting court", sport="tennis", hourly_rate=Decimal("500.00"))
        tz = timezone.get_current_timezone()
        for hour, status in [(9, "confirmed"), (11, "cancelled"), (13, "draft")]:
            Booking.objects.create(
                court=court, walkin_name="Guest", status=status,
                start_datetime=timezone.make_aware(datetime.combine(self.today, time(hour)), tz),
            )
        complete_sale(self.guest_sale().pk)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["confirmed_booking_value"], Decimal("500.00"))
        self.assertEqual(response.context["completed_sales_total"], Decimal("25.00"))
        self.assertContains(response, "Confirmed Booking Value")
        self.assertContains(response, "payment collection not recorded")
        self.assertContains(response, "Completed Shop Sales")
        self.assertContains(response, "Completed Bar Sales")
        self.assertNotContains(response, "Court Booking Revenue")
        self.assertNotContains(response, "Outstanding Dues")
        self.assertNotContains(response, "No pending dues")

    def test_dashboard_active_members_excludes_expired_future_suspended_and_inactive_plan(self):
        active_plan = MembershipPlan.objects.create(tier="silver", name="Active plan")
        inactive_plan = MembershipPlan.objects.create(tier="gold", name="Inactive plan", active=False)
        profiles = [
            {"name": "Eligible", "plan": active_plan},
            {"name": "Expired", "plan": active_plan, "membership_end": self.today - timedelta(days=1)},
            {"name": "Future", "plan": active_plan, "membership_start": self.today + timedelta(days=1)},
            {"name": "Suspended", "plan": active_plan, "is_suspended": True},
            {"name": "Inactive plan", "plan": inactive_plan},
            {"name": "Not club member", "plan": active_plan, "is_club_member": False},
            {"name": "No plan"},
        ]
        for values in profiles:
            Member.objects.create(**values)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["active_members"], 1)
        self.assertEqual(response.context["total_members"], 7)

    def test_dashboard_shows_live_alert_links_and_saved_recent_sale(self):
        Product.objects.filter(pk=self.shop.pk).update(stock_quantity=2)
        sale = complete_sale(self.guest_sale({self.bar.pk: 2}).pk)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Dashboard racket")
        self.assertContains(response, self.shop.get_absolute_url())
        self.assertContains(response, reverse("commerce:sale_detail", args=[sale.pk]))
        self.assertContains(response, "Completed Sales by Creation Date")

    def test_active_member_count_resolves_effective_plan_without_rewriting_profile(self):
        inactive = MembershipPlan.objects.create(tier="silver", name="Inactive baseline", active=False)
        active = MembershipPlan.objects.create(tier="gold", name="Active effective", active=True)
        member = Member.objects.create(name="Scheduled member", plan=inactive)
        MemberPlanChange.objects.create(member=member, plan=active, effective_date=self.today)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["active_members"], 1)
        member.refresh_from_db()
        self.assertEqual(member.plan_id, inactive.pk)
