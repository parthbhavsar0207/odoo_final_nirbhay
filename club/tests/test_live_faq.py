"""Concierge facts must follow current shared records rather than demo constants."""
from decimal import Decimal
from unittest import skipUnless

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from club.models import Court, Member, MembershipPlan
from commerce.models import Product


@skipUnless(connection.vendor == "postgresql", "Requires shared PostgreSQL records")
class LiveConciergeTests(TestCase):
    def answer(self, query, topic):
        response = self.client.get(reverse("club:help_bot_faq"), {"q": query})
        self.assertEqual(response.status_code, 200)
        return next(faq["answer"] for faq in response.json()["faqs"] if faq["id"] == topic)

    def test_plan_answer_uses_live_prices_and_discounts_after_edit(self):
        plan = MembershipPlan.objects.create(
            tier="silver", name="Current Silver", membership_fee=Decimal("3000.00"),
            court_hourly_rate=Decimal("200.00"), shop_discount_percent=Decimal("10.00"),
            bar_discount_percent=Decimal("5.00"),
        )
        answer = self.answer("plans", "plans")
        self.assertIn("₹200.00/hour", answer)
        self.assertNotIn("₹150", answer)
        MembershipPlan.objects.filter(pk=plan.pk).update(
            name="Changed Silver", court_hourly_rate=Decimal("275.00"),
            shop_discount_percent=Decimal("12.00"), bar_discount_percent=Decimal("6.00"),
        )
        answer = self.answer("plans", "plans")
        self.assertIn("Changed Silver", answer)
        self.assertIn("₹275.00/hour", answer)
        self.assertIn("shop 12.00%", answer)
        self.assertIn("bar 6.00%", answer)
        self.assertNotIn("10.00%", answer)

    def test_inactive_plan_is_not_advertised(self):
        MembershipPlan.objects.create(tier="gold", name="Retired Gold", active=False)
        self.assertIn("No active membership plans", self.answer("plans", "plans"))

    def test_new_custom_tier_answers_are_supported_without_fixed_tier_rates(self):
        MembershipPlan.objects.create(
            tier="platinum", name="Active Platinum", court_hourly_rate=Decimal("80.00"),
        )
        self.assertIn("Active Platinum", self.answer("platinum", "plans"))

    def test_sports_answer_only_claims_configured_active_facilities(self):
        Court.objects.create(name="Active Tennis", sport="tennis", active=True)
        Court.objects.create(name="Inactive Swimming", sport="swimming", active=False)
        answer = self.answer("sports", "sports")
        self.assertIn("Tennis", answer)
        self.assertNotIn("Swimming", answer)
        self.assertNotIn("world-class", answer)

    def test_no_facilities_have_clear_empty_state(self):
        self.assertIn("facilities: none", self.answer("sports", "sports"))

    def test_commerce_chip_uses_live_active_counts_and_explains_checkout(self):
        Product.objects.create(name="Shop one", category="shop", price=Decimal("10.00"), stock_quantity=1)
        Product.objects.create(name="Bar one", category="bar", price=Decimal("5.00"), stock_quantity=2)
        Product.objects.create(name="Retired bar", category="bar", price=Decimal("5.00"), is_active=False)
        answer = self.answer("commerce", "commerce")
        self.assertIn("Pro Shop has 1 active products", answer)
        self.assertIn("Bar has 1", answer)
        self.assertIn("Select Member sale", answer)

    def test_response_does_not_query_or_expose_private_member_details(self):
        Member.objects.create(name="Private Concierge Person", email="private-concierge@example.com")
        response = self.client.get(reverse("club:help_bot_faq"))
        self.assertNotContains(response, "Private Concierge Person")
        self.assertNotContains(response, "private-concierge@example.com")
