"""Shared membership discounts and counter integration on real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.db.models.deletion import ProtectedError
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from club.models import Member, MembershipPlan
from commerce.calculations import calculate_sale_line, calculate_sale_totals
from commerce.counter_forms import GuestSaleForm, MemberSaleForm
from commerce.models import Product, Sale
from commerce.services import cancel_sale, complete_sale, create_guest_sale, create_sale


class MemberCalculationTests(SimpleTestCase):
    def test_fractional_paise_discount_rounds_half_up_on_line_subtotal(self):
        line = calculate_sale_line(
            unit_price=Decimal("0.05"), quantity=1, discount_percent=Decimal("10.00"),
        )
        self.assertEqual(line.discount, Decimal("0.01"))
        self.assertEqual(line.line_total, Decimal("0.04"))

    def test_rounding_is_per_whole_line_not_per_unit(self):
        line = calculate_sale_line(
            unit_price=Decimal("0.05"), quantity=2, discount_percent=Decimal("10.00"),
        )
        self.assertEqual(line.subtotal, Decimal("0.10"))
        self.assertEqual(line.discount, Decimal("0.01"))
        self.assertEqual(line.line_total, Decimal("0.09"))

    def test_zero_and_full_discount_have_exact_decimal_amounts(self):
        for percent, expected in [(Decimal("0.00"), Decimal("25.00")),
                                  (Decimal("100.00"), Decimal("0.00"))]:
            with self.subTest(percent=percent):
                line = calculate_sale_line(
                    unit_price=Decimal("12.50"), quantity=2, discount_percent=percent,
                )
                self.assertEqual(line.line_total, expected)
                self.assertIsInstance(line.discount, Decimal)

    def test_invalid_discount_types_ranges_and_precision_are_rejected(self):
        for percent in [10.0, "10.00", True, Decimal("-0.01"), Decimal("100.01"),
                        Decimal("NaN"), Decimal("Infinity"), Decimal("1.001")]:
            with self.subTest(percent=percent), self.assertRaises(ValidationError):
                calculate_sale_line(
                    unit_price=Decimal("12.50"), quantity=2, discount_percent=percent,
                )

    def test_totals_sum_saved_line_discounts_without_rerounding_percentage(self):
        lines = [
            calculate_sale_line(unit_price=Decimal("0.05"), quantity=1,
                                discount_percent=Decimal("10.00")),
            calculate_sale_line(unit_price=Decimal("0.05"), quantity=1,
                                discount_percent=Decimal("10.00")),
        ]
        total = calculate_sale_totals(lines)
        self.assertEqual((total.subtotal, total.discount, total.total),
                         (Decimal("0.10"), Decimal("0.02"), Decimal("0.08")))


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL member sales")
class MemberSaleDatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.plan = MembershipPlan.objects.create(
            tier="silver", name="Configured Silver", shop_discount_percent=Decimal("10.00"),
            bar_discount_percent=Decimal("5.00"), active=True,
        )
        cls.member = Member.objects.create(
            name="Silver purchaser", plan=cls.plan, membership_start=cls.today - timedelta(days=1),
            membership_end=cls.today + timedelta(days=1), is_club_member=True,
        )
        cls.shop = Product.objects.create(
            name="Shop item", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )
        cls.bar = Product.objects.create(
            name="Bar item", category="bar", price=Decimal("2.00"), stock_quantity=10,
        )

    def draft(self, quantities=None, member_id=None):
        return create_sale(
            quantities=quantities or {self.shop.pk: 2},
            payment_method=Sale.PaymentMethod.CASH,
            member_id=self.member.pk if member_id is None else member_id,
        )

    def assert_stock_and_draft_unchanged(self, sale):
        self.shop.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(sale.total, Decimal("0.00"))
        self.assertEqual(sale.items.get().unit_price, Decimal("0.00"))

    def test_draft_links_real_member_without_deducting_or_pricing(self):
        sale = self.draft()
        self.assertEqual(sale.member, self.member)
        self.assert_stock_and_draft_unchanged(sale)

    def test_configured_tiers_use_separate_shop_and_bar_percentages(self):
        # Values are demonstration fixtures, never official hardcoded service rates.
        for tier, shop_percent, bar_percent in [
            ("gold", "20.00", "15.00"), ("silver", "10.00", "5.00"),
            ("junior", "15.00", "0.00"),
        ]:
            with self.subTest(tier=tier):
                self.plan.tier = tier
                self.plan.shop_discount_percent = Decimal(shop_percent)
                self.plan.bar_discount_percent = Decimal(bar_percent)
                self.plan.save()
                sale = complete_sale(self.draft({self.shop.pk: 2, self.bar.pk: 2}).pk)
                shop_item = sale.items.get(product=self.shop)
                bar_item = sale.items.get(product=self.bar)
                expected_shop = Decimal("25.00") * Decimal(shop_percent) / Decimal("100")
                expected_bar = Decimal("4.00") * Decimal(bar_percent) / Decimal("100")
                self.assertEqual(shop_item.discount, expected_shop)
                self.assertEqual(bar_item.discount, expected_bar)
                self.assertEqual(sale.subtotal, Decimal("29.00"))
                self.assertEqual(sale.discount, expected_shop + expected_bar)
                self.assertEqual(sale.total, Decimal("29.00") - expected_shop - expected_bar)
                cancel_sale(sale.pk)

    def test_guests_remain_unlinked_and_have_zero_discount(self):
        sale = complete_sale(create_guest_sale(
            quantities={self.shop.pk: 2}, payment_method=Sale.PaymentMethod.UPI,
        ).pk)
        self.assertIsNone(sale.member_id)
        self.assertEqual(sale.discount, Decimal("0.00"))
        self.assertEqual(sale.total, Decimal("25.00"))

    def test_invalid_or_missing_member_does_not_create_partial_sale(self):
        for member_id in [True, "1", -1, 0, self.member.pk + 1000]:
            with self.subTest(member_id=member_id), self.assertRaises(ValidationError):
                create_sale(quantities={self.shop.pk: 1}, payment_method="cash",
                            member_id=member_id)
        self.assertEqual(Sale.objects.count(), 0)

    def test_member_deletion_is_protected_by_sale_history(self):
        self.draft()
        with self.assertRaises(ProtectedError):
            self.member.delete()

    def test_ineligible_profiles_retain_member_link_but_get_no_discount(self):
        profiles = [
            {"is_suspended": True},
            {"is_club_member": False},
            {"membership_end": self.today - timedelta(days=1)},
            {"membership_start": self.today + timedelta(days=1)},
            {"plan": None},
        ]
        baseline = {
            "is_suspended": False, "is_club_member": True, "plan": self.plan,
            "membership_start": self.today - timedelta(days=1),
            "membership_end": self.today + timedelta(days=1),
        }
        for changes in profiles:
            with self.subTest(profile=changes):
                for name, value in {**baseline, **changes}.items():
                    setattr(self.member, name, value)
                self.member.save()
                sale = complete_sale(self.draft().pk)
                self.assertEqual(sale.member_id, self.member.pk)
                self.assertEqual(sale.discount, Decimal("0.00"))
                self.assertEqual(sale.total, Decimal("25.00"))
                cancel_sale(sale.pk)

    def test_inactive_plan_gets_no_discount(self):
        self.plan.active = False
        self.plan.save()
        sale = complete_sale(self.draft().pk)
        self.assertEqual(sale.discount, Decimal("0.00"))
        self.assertEqual(sale.total, Decimal("25.00"))

    def test_missing_dates_follow_shared_open_ended_membership_semantics(self):
        self.member.membership_start = None
        self.member.membership_end = None
        self.member.save()
        sale = complete_sale(self.draft().pk)
        self.assertEqual(sale.discount, Decimal("2.50"))

    def test_membership_dates_include_start_and_end_day(self):
        self.member.membership_start = self.today
        self.member.membership_end = self.today
        self.member.save()
        sale = complete_sale(self.draft().pk)
        self.assertEqual(sale.discount, Decimal("2.50"))

    def test_eligibility_uses_completion_date_not_draft_date(self):
        sale = self.draft()
        with patch("commerce.services.timezone.localdate",
                   return_value=self.today + timedelta(days=2)):
            completed = complete_sale(sale.pk)
        self.assertEqual(completed.discount, Decimal("0.00"))

    def test_plan_and_product_changes_before_completion_are_snapshotted(self):
        sale = self.draft()
        MembershipPlan.objects.filter(pk=self.plan.pk).update(shop_discount_percent=Decimal("20.00"))
        Product.objects.filter(pk=self.shop.pk).update(price=Decimal("15.00"))
        completed = complete_sale(sale.pk)
        item = completed.items.get()
        self.assertEqual((item.unit_price, item.discount, item.line_total),
                         (Decimal("15.00"), Decimal("6.00"), Decimal("24.00")))

    def test_member_plan_change_before_completion_reads_new_plan(self):
        sale = self.draft()
        new_plan = MembershipPlan.objects.create(
            tier="gold", name="Changed plan", shop_discount_percent=Decimal("30.00"),
            bar_discount_percent=Decimal("0.00"),
        )
        Member.objects.filter(pk=self.member.pk).update(plan=new_plan)
        completed = complete_sale(sale.pk)
        self.assertEqual(completed.discount, Decimal("7.50"))
        self.assertEqual(completed.total, Decimal("17.50"))

    def test_completed_retry_keeps_discount_after_member_plan_and_price_changes(self):
        sale = complete_sale(self.draft().pk)
        Member.objects.filter(pk=self.member.pk).update(is_suspended=True, plan=None)
        MembershipPlan.objects.filter(pk=self.plan.pk).update(shop_discount_percent=Decimal("101.00"))
        Product.objects.filter(pk=self.shop.pk).update(price=Decimal("99.00"))
        retried = complete_sale(sale.pk)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 8)
        self.assertEqual((retried.subtotal, retried.discount, retried.total),
                         (Decimal("25.00"), Decimal("2.50"), Decimal("22.50")))
        self.assertEqual(retried.items.get().discount, Decimal("2.50"))

    def test_invalid_stored_plan_rates_abort_before_any_inventory_write(self):
        for rate in [Decimal("-1.00"), Decimal("101.00")]:
            with self.subTest(rate=rate):
                MembershipPlan.objects.filter(pk=self.plan.pk).update(shop_discount_percent=rate)
                sale = self.draft()
                with self.assertRaises(ValidationError):
                    complete_sale(sale.pk)
                self.assert_stock_and_draft_unchanged(sale)

    def test_post_deduction_failure_rolls_back_discounts_and_stock(self):
        sale = self.draft()
        with patch("commerce.services.SaleItem.objects.bulk_update",
                   side_effect=RuntimeError("snapshot write failed")):
            with self.assertRaises(RuntimeError):
                complete_sale(sale.pk)
        self.assert_stock_and_draft_unchanged(sale)

    def test_member_cancellation_restores_once_and_keeps_discount_snapshots(self):
        sale = complete_sale(self.draft().pk)
        cancel_sale(sale.pk)
        cancel_sale(sale.pk)
        self.shop.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.shop.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.CANCELLED)
        self.assertEqual(sale.member_id, self.member.pk)
        self.assertEqual((sale.discount, sale.total),
                         (Decimal("2.50"), Decimal("22.50")))
        self.assertEqual(sale.items.get().discount, Decimal("2.50"))


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL member counter")
class MemberCounterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(username="member-counter-staff", is_staff=True)
        cls.nonstaff = get_user_model().objects.create_user(username="member-counter-customer")
        cls.plan = MembershipPlan.objects.create(
            tier="silver", name="Silver", shop_discount_percent=Decimal("10.00"),
            bar_discount_percent=Decimal("5.00"),
        )
        cls.member = Member.objects.create(name="Counter member", plan=cls.plan)
        cls.product = Product.objects.create(
            name="Member counter product", category="shop",
            price=Decimal("12.50"), stock_quantity=10,
        )

    def data(self, **changes):
        values = {"member": str(self.member.pk), "product": str(self.product.pk),
                  "quantity": "2", "payment_method": "cash"}
        values.update(changes)
        return values

    def test_member_form_adds_real_member_field_without_changing_guest_form(self):
        self.assertEqual(set(MemberSaleForm().fields),
                         {"member", "product", "quantity", "payment_method"})
        self.assertEqual(set(GuestSaleForm().fields), {"product", "quantity", "payment_method"})
        form = MemberSaleForm(self.data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["member"], self.member)

    def test_member_routes_work_without_staff_authentication(self):
        for user in [None, self.nonstaff, self.staff]:
            with self.subTest(user=user):
                client = Client()
                if user is not None:
                    client.force_login(user)
                self.assertEqual(client.get(reverse("commerce:member_counter")).status_code, 200)
                response = client.post(reverse("commerce:member_sale_create"), self.data())
                sale = Sale.objects.latest("pk")
                self.assertEqual(sale.member_id, self.member.pk)
                detail_url = reverse("commerce:sale_detail", args=[sale.pk])
                self.assertRedirects(response, detail_url, fetch_redirect_response=False)
                self.assertEqual(client.get(detail_url).status_code, 200)
                response = client.post(reverse("commerce:sale_complete", args=[sale.pk]))
                self.assertRedirects(response, detail_url, fetch_redirect_response=False)
                sale.refresh_from_db()
                self.product.refresh_from_db()
                self.assertEqual(sale.total, Decimal("22.50"))
                self.assertEqual(self.product.stock_quantity, 8)
                response = client.post(reverse("commerce:sale_cancel", args=[sale.pk]))
                self.assertRedirects(response, detail_url, fetch_redirect_response=False)
                self.product.refresh_from_db()
                self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(Sale.objects.count(), 3)

    def test_member_screen_renders_real_form_and_named_post_with_csrf(self):
        response = self.client.get(reverse("commerce:member_counter"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "commerce/index.html")
        self.assertIsInstance(response.context["form"], MemberSaleForm)
        self.assertContains(response, 'name="member"')
        self.assertContains(response, "Counter member")
        self.assertContains(response, reverse("commerce:member_sale_create"))
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_member_routes_enforce_safe_get_and_post_only_creation(self):
        self.assertEqual(self.client.head(reverse("commerce:member_counter")).status_code, 200)
        self.assertEqual(self.client.post(reverse("commerce:member_counter"), self.data()).status_code, 405)
        for method in ["get", "head", "put", "delete"]:
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(
                    reverse("commerce:member_sale_create")).status_code, 405)

    def test_valid_member_creation_and_existing_actions_complete_then_cancel(self):
        response = self.client.post(reverse("commerce:member_sale_create"), self.data(
            total="0.01", discount="100", next="https://example.com/"))
        sale = Sale.objects.get()
        self.assertRedirects(response, reverse("commerce:sale_detail", args=[sale.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(sale.member_id, self.member.pk)
        self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        detail = self.client.get(reverse("commerce:sale_detail", args=[sale.pk]))
        self.assertContains(detail, "Counter member")
        self.assertContains(detail, "22.50")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)
        self.client.post(reverse("commerce:sale_cancel", args=[sale.pk]))
        self.client.post(reverse("commerce:sale_cancel", args=[sale.pk]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_invalid_member_returns_visible_bound_error_without_draft(self):
        for value in ["", "missing", str(self.member.pk + 1000)]:
            with self.subTest(member=value):
                response = self.client.post(reverse("commerce:member_sale_create"),
                                            self.data(member=value))
                self.assertEqual(response.status_code, 400)
                self.assertIn("member", response.context["form"].errors)
                self.assertContains(response, 'name="member"', status_code=400)
        self.assertEqual(Sale.objects.count(), 0)

    def test_member_creation_requires_csrf_and_valid_token_allows_submission(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("commerce:member_sale_create"), self.data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Sale.objects.count(), 0)
        client.get(reverse("commerce:member_counter"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("commerce:member_sale_create"),
                               self.data(csrfmiddlewaretoken=token))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Sale.objects.get().member_id, self.member.pk)

    def test_invalid_plan_rate_is_controlled_conflict_with_unchanged_stock(self):
        response = self.client.post(reverse("commerce:member_sale_create"), self.data())
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        MembershipPlan.objects.filter(pk=self.plan.pk).update(shop_discount_percent=Decimal("101.00"))
        response = self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.context["error_message"])
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.DRAFT)


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL member row locks")
class MemberSaleConcurrencyTests(TransactionTestCase):
    def test_same_member_sale_completes_once_under_concurrent_requests(self):
        plan = MembershipPlan.objects.create(
            tier="silver", name="Concurrent Silver", shop_discount_percent=Decimal("10.00"),
        )
        member = Member.objects.create(name="Concurrent member", plan=plan)
        product = Product.objects.create(
            name="Concurrent member item", category="shop",
            price=Decimal("12.50"), stock_quantity=10,
        )
        sale = create_sale(quantities={product.pk: 2}, payment_method="cash", member_id=member.pk)
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '5s'")
                    cursor.execute("SET statement_timeout TO '10s'")
                barrier.wait(timeout=5)
                return complete_sale(sale.pk).total
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results, [Decimal("22.50"), Decimal("22.50")])
        product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(product.stock_quantity, 8)
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.items.get().discount, Decimal("2.50"))
