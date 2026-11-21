"""Plan validation and date-effective assignments on shared PostgreSQL models."""
from datetime import timedelta, datetime, time
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from club.forms import MembershipPlanForm, MemberChangePlanForm, MemberForm
from club.models import Member, MembershipPlan, MemberPlanChange, Court, Booking
from club.plan_changes import change_membership_plan
from commerce.models import Product, Sale
from commerce.services import create_sale, complete_sale, cancel_sale


@skipUnless(connection.vendor == "postgresql", "Requires the shared PostgreSQL environment")
class PlanValidationTests(TestCase):
    def values(self, **changes):
        values = dict(tier="silver", name="Silver", membership_fee="3000.00",
                      court_hourly_rate="200.00", shop_discount_percent="10.00",
                      bar_discount_percent="5.00", active="on")
        values.update(changes)
        return values

    def test_plan_form_rejects_negative_prices_and_out_of_range_percentages(self):
        for field, value in [("membership_fee", "-0.01"), ("court_hourly_rate", "-0.01"),
                             ("shop_discount_percent", "-0.01"), ("shop_discount_percent", "100.01"),
                             ("bar_discount_percent", "-0.01"), ("bar_discount_percent", "100.01")]:
            with self.subTest(field=field, value=value):
                form = MembershipPlanForm(self.values(**{field: value}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_model_full_clean_rejects_invalid_money_and_rates(self):
        for changes in [{"membership_fee": Decimal("-1.00")},
                        {"court_hourly_rate": Decimal("-1.00")},
                        {"shop_discount_percent": Decimal("101.00")},
                        {"bar_discount_percent": Decimal("-1.00")}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                MembershipPlan(tier="gold", name="Invalid", **changes).full_clean()

    def test_zero_prices_and_zero_or_full_discount_are_valid(self):
        form = MembershipPlanForm(self.values(membership_fee="0.00", court_hourly_rate="0.00",
                                              shop_discount_percent="100.00", bar_discount_percent="0.00"))
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save()
        self.assertEqual(plan.shop_discount_percent, Decimal("100.00"))

    def test_plan_create_invalid_post_does_not_persist(self):
        response = self.client.post(reverse("club:plan_create"), self.values(shop_discount_percent="101.00"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(MembershipPlan.objects.count(), 0)


@skipUnless(connection.vendor == "postgresql", "Requires shared PostgreSQL plan changes")
class ScheduledPlanChangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.old = MembershipPlan.objects.create(tier="silver", name="Original Silver",
            membership_fee=Decimal("3000.00"), court_hourly_rate=Decimal("200.00"),
            shop_discount_percent=Decimal("10.00"), bar_discount_percent=Decimal("5.00"))
        cls.new = MembershipPlan.objects.create(tier="gold", name="Future Gold",
            membership_fee=Decimal("5000.00"), court_hourly_rate=Decimal("50.00"),
            shop_discount_percent=Decimal("20.00"), bar_discount_percent=Decimal("15.00"))
        cls.member = Member.objects.create(name="Scheduled member", plan=cls.old,
            membership_start=cls.today-timedelta(days=10), membership_end=cls.today+timedelta(days=30))
        cls.court = Court.objects.create(name="Schedule court", sport="tennis",
            hourly_rate=Decimal("500.00"))
        cls.product = Product.objects.create(name="Schedule product", category="shop",
            price=Decimal("100.00"), stock_quantity=10)

    def schedule(self, offset=1, plan=None):
        return change_membership_plan(member_id=self.member.pk, plan_id=(plan or self.new).pk,
            effective_date=self.today+timedelta(days=offset), notes="Approved test")

    def booking(self, day):
        start = timezone.make_aware(datetime.combine(day, time(9)))
        return Booking(court=self.court, booked_by_member=self.member, start_datetime=start)

    def test_future_change_preserves_current_plan_and_membership_dates(self):
        original_dates = (self.member.membership_start, self.member.membership_end)
        change = self.schedule()
        self.member.refresh_from_db()
        self.assertEqual(self.member.plan, self.old)
        self.assertEqual((self.member.membership_start, self.member.membership_end), original_dates)
        self.assertEqual(self.member.effective_plan_on_date(self.today), self.old)
        self.assertEqual(self.member.effective_plan_on_date(change.effective_date), self.new)
        self.assertEqual(self.member.pending_plan_changes.get(), change)

    def test_immediate_change_uses_resolver_without_rewriting_original_membership(self):
        self.schedule(offset=0)
        self.member.refresh_from_db()
        self.assertEqual(self.member.current_plan, self.new)
        self.assertEqual(self.member.plan, self.old)

    def test_sequential_dated_changes_choose_latest_applicable_assignment(self):
        self.schedule(offset=1)
        later = MembershipPlan.objects.create(tier="custom", name="Later custom",
            court_hourly_rate=Decimal("100.00"))
        self.schedule(offset=4, plan=later)
        self.assertEqual(self.member.effective_plan_on_date(self.today), self.old)
        self.assertEqual(self.member.effective_plan_on_date(self.today+timedelta(days=2)), self.new)
        self.assertEqual(self.member.effective_plan_on_date(self.today+timedelta(days=4)), later)

    def test_duplicate_date_rejected_atomically(self):
        self.schedule()
        with self.assertRaises(ValidationError):
            self.schedule()
        self.assertEqual(MemberPlanChange.objects.count(), 1)

    def test_past_or_outside_membership_dates_rejected(self):
        for offset in [-1, 31]:
            with self.subTest(offset=offset), self.assertRaises(ValidationError):
                self.schedule(offset=offset)
        self.assertEqual(MemberPlanChange.objects.count(), 0)

    def test_inactive_or_invalid_target_plan_rejected(self):
        MembershipPlan.objects.filter(pk=self.new.pk).update(active=False)
        with self.assertRaises(ValidationError):
            self.schedule()
        MembershipPlan.objects.filter(pk=self.new.pk).update(active=True, shop_discount_percent=Decimal("101.00"))
        with self.assertRaises(ValidationError):
            self.schedule()
        self.assertEqual(MemberPlanChange.objects.count(), 0)

    def test_plan_change_view_schedules_future_and_keeps_current_benefits(self):
        response = self.client.post(reverse("club:member_change_plan", args=[self.member.pk]), {
            "new_plan": self.new.pk, "effective_date": (self.today+timedelta(days=2)).isoformat(),
            "confirm_change": "on", "notes": "Future transition",
        })
        self.assertRedirects(response, reverse("club:member_list"), fetch_redirect_response=False)
        self.member.refresh_from_db()
        self.assertEqual(self.member.current_plan, self.old)
        self.assertEqual(self.member.pending_plan_changes.get().plan, self.new)
        page = self.client.get(reverse("club:member_change_plan", args=[self.member.pk]))
        self.assertContains(page, "Scheduled:")
        self.assertContains(page, "Future Gold")

    def test_effective_plan_used_for_booking_date_and_eligibility(self):
        self.schedule()
        self.assertEqual(self.booking(self.today).calculate_price(), Decimal("200.00"))
        self.assertEqual(self.booking(self.today+timedelta(days=1)).calculate_price(), Decimal("50.00"))
        for changes in [{"is_club_member": False}, {"is_suspended": True}]:
            with self.subTest(changes=changes):
                for key, value in changes.items():
                    setattr(self.member, key, value)
                self.assertEqual(self.booking(self.today).calculate_price(), Decimal("500.00"))
                self.member.is_club_member = True
                self.member.is_suspended = False
        MembershipPlan.objects.filter(pk=self.new.pk).update(active=False)
        self.assertEqual(self.booking(self.today+timedelta(days=1)).calculate_price(), Decimal("500.00"))

    def test_dated_changes_preserve_saved_booking_and_sale_amounts(self):
        sale = complete_sale(create_sale(quantities={self.product.pk: 1}, payment_method="cash",
            member_id=self.member.pk).pk)
        old_total = sale.total
        booking = self.booking(self.today)
        booking.status = "confirmed"
        booking.save()
        old_price = booking.price
        self.schedule()
        self.assertEqual(complete_sale(sale.pk).total, old_total)
        booking.refresh_from_db()
        self.assertEqual(booking.price, old_price)

    def test_commerce_uses_new_assignment_only_after_effective_date(self):
        self.schedule()
        old_sale = complete_sale(create_sale(quantities={self.product.pk: 1}, payment_method="cash",
            member_id=self.member.pk).pk)
        self.assertEqual(old_sale.discount, Decimal("10.00"))
        with patch("commerce.services.timezone.localdate", return_value=self.today+timedelta(days=1)):
            new_sale = complete_sale(create_sale(quantities={self.product.pk: 1}, payment_method="cash",
                member_id=self.member.pk).pk)
        self.assertEqual(new_sale.discount, Decimal("20.00"))
        old_sale.refresh_from_db()
        self.assertEqual(old_sale.discount, Decimal("10.00"))

    def test_direct_member_edit_cannot_rewrite_plan_baseline_after_change(self):
        self.schedule()
        form = MemberForm(instance=self.member)
        self.assertTrue(form.fields["plan"].disabled)

    def test_admin_edit_preserves_baseline_plan_after_scheduled_change(self):
        change = self.schedule()
        operator = get_user_model().objects.create(
            username="plan-admin-regression", is_staff=True, is_superuser=True,
        )
        self.client.force_login(operator)
        url = reverse("admin:club_member_change", args=[self.member.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["adminform"].form, MemberForm)
        self.assertTrue(response.context["adminform"].form.fields["plan"].disabled)

        response = self.client.post(url, {
            "name": "Updated scheduled member",
            "email": self.member.email,
            "phone": self.member.phone,
            "contact_details": self.member.contact_details,
            "plan": self.new.pk,
            "membership_start": self.member.membership_start.isoformat(),
            "membership_end": self.member.membership_end.isoformat(),
            "is_club_member": "on",
            "_save": "Save",
        })
        self.assertRedirects(response, reverse("admin:club_member_changelist"), fetch_redirect_response=False)
        self.member.refresh_from_db()
        self.assertEqual(self.member.name, "Updated scheduled member")
        self.assertEqual(self.member.plan_id, self.old.pk)
        self.assertEqual(self.member.current_plan, self.old)
        self.assertEqual(self.member.effective_plan_on_date(change.effective_date), self.new)
        self.assertEqual(self.member.plan_changes.count(), 1)

    def test_member_tier_filter_uses_current_effective_plan(self):
        self.schedule(offset=0)
        response = self.client.get(reverse("club:member_list"), {"tier": "gold"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["members"]), [self.member])
        response = self.client.get(reverse("club:member_list"), {"tier": "silver"})
        self.assertEqual(list(response.context["members"]), [])

    def test_form_and_csrf_protect_plan_transition(self):
        form = MemberChangePlanForm({"new_plan": self.new.pk,
            "effective_date": (self.today-timedelta(days=1)).isoformat(), "confirm_change": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("effective_date", form.errors)
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("club:member_change_plan", args=[self.member.pk]), {
            "new_plan": self.new.pk, "effective_date": self.today.isoformat(), "confirm_change": "on"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(MemberPlanChange.objects.count(), 0)
