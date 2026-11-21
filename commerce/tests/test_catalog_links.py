"""Product search suggestions must open a usable, preselected counter form."""

from decimal import Decimal
from unittest import skipUnless

from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from club.models import Member, MembershipPlan
from club.forms import MembershipPlanForm
from commerce.counter_forms import GuestSaleForm, MemberSaleForm
from commerce.models import Product, Sale
from commerce.services import create_sale, complete_sale, cancel_sale


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL catalogue integration")
class ProductSearchCounterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Searchable racket", category="shop", price=Decimal("1499.50"),
            stock_quantity=12,
        )
        cls.other_product = Product.objects.create(
            name="Searchable refreshment", category="bar", price=Decimal("60.00"),
            stock_quantity=7,
        )
        cls.inactive_product = Product.objects.create(
            name="Searchable retired racket", category="shop", price=Decimal("99.00"),
            stock_quantity=20, is_active=False,
        )
        cls.plan = MembershipPlan.objects.create(
            tier="silver", name="Silver plan", shop_discount_percent=Decimal("10.00"),
            bar_discount_percent=Decimal("5.00"),
        )
        cls.member = Member.objects.create(
            name="PRIVATE_MEMBER_TOKEN", email="private-token@example.com",
            phone="PRIVATE_PHONE_TOKEN", plan=cls.plan,
        )

    def test_product_absolute_url_names_counter_and_preserves_product_selection(self):
        self.assertEqual(
            self.product.get_absolute_url(),
            reverse("commerce:guest_counter") + f"?product={self.product.pk}#guest-sale-form",
        )

    def test_header_product_suggestions_include_real_price_stock_and_specific_links(self):
        response = self.client.get(reverse("club:search_suggestions"), {"q": "Searchable"})
        self.assertEqual(response.status_code, 200)
        products = [
            item for item in response.json()["suggestions"] if item["type"] == "Shop & Bar"
        ]
        self.assertEqual(
            {item["title"] for item in products},
            {self.product.name, self.other_product.name},
        )
        product_result = next(item for item in products if item["title"] == self.product.name)
        self.assertEqual(product_result["url"], self.product.get_absolute_url())
        self.assertIn("1499.50", product_result["subtitle"])
        self.assertIn("12", product_result["subtitle"])
        self.assertFalse(any(item["title"] == self.inactive_product.name for item in products))

    def test_following_suggestion_selects_actual_product_without_creating_a_sale(self):
        results = self.client.get(
            reverse("club:search_suggestions"), {"q": "Searchable racket"},
        ).json()["suggestions"]
        result = next(item for item in results if item["type"] == "Shop & Bar")
        response = self.client.get(result["url"])
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], GuestSaleForm)
        self.assertEqual(str(response.context["form"]["product"].value()), str(self.product.pk))
        self.assertEqual(str(response.context["form"]["quantity"].value()), "1")
        self.assertTemplateUsed(response, "commerce/index.html")
        self.assertEqual(Sale.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 12)

    def test_catalog_aliases_accept_product_selection_without_login(self):
        for route in ["commerce:index", "commerce:shop", "commerce:guest_counter"]:
            with self.subTest(route=route):
                response = self.client.get(reverse(route), {"product": self.product.pk})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    str(response.context["form"]["product"].value()), str(self.product.pk),
                )
                self.assertEqual(str(response.context["form"]["quantity"].value()), "1")
        self.assertEqual(Sale.objects.count(), 0)

    def test_member_counter_keeps_member_form_and_selected_product(self):
        response = self.client.get(
            reverse("commerce:member_counter"), {"product": self.other_product.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], MemberSaleForm)
        self.assertTrue(response.context["member_mode"])
        self.assertEqual(
            str(response.context["form"]["product"].value()), str(self.other_product.pk),
        )
        self.assertEqual(str(response.context["form"]["quantity"].value()), "1")
        self.assertIsNone(response.context["form"]["member"].value())

    def test_missing_malformed_and_inactive_product_links_return_404_without_mutation(self):
        missing_id = max(self.product.pk, self.other_product.pk, self.inactive_product.pk) + 1000
        for route in ["commerce:guest_counter", "commerce:member_counter"]:
            for value in ["invalid", "0", "-1", "1.5", str(missing_id), str(self.inactive_product.pk)]:
                with self.subTest(route=route, product=value):
                    response = self.client.get(reverse(route), {"product": value})
                    self.assertEqual(response.status_code, 404)
        self.assertEqual(Sale.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 12)

    def test_unselected_counter_retains_normal_unbound_form(self):
        response = self.client.get(reverse("commerce:guest_counter"))
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertFalse(form.is_bound)
        self.assertIsNone(form["product"].value())
        self.assertEqual(
            set(form.fields["product"].queryset.values_list("pk", flat=True)),
            {self.product.pk, self.other_product.pk},
        )

    def test_post_uses_validated_submitted_product_not_the_query_string(self):
        response = self.client.post(
            reverse("commerce:sale_create") + f"?product={self.product.pk}",
            {"product": self.other_product.pk, "quantity": "2", "payment_method": "cash"},
        )
        sale = Sale.objects.get()
        self.assertRedirects(
            response, reverse("commerce:sale_detail", args=[sale.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(sale.items.get().product_id, self.other_product.pk)
        self.assertEqual(sale.items.get().quantity, 2)
        self.assertEqual(sale.total, Decimal("0.00"))
        self.product.refresh_from_db()
        self.other_product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 12)
        self.assertEqual(self.other_product.stock_quantity, 7)

    def test_preselected_counter_still_requires_csrf_on_creation(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get(
            reverse("commerce:guest_counter"), {"product": self.product.pk},
        )
        self.assertEqual(response.status_code, 200)
        data = {"product": self.product.pk, "quantity": "1", "payment_method": "cash"}
        self.assertEqual(client.post(reverse("commerce:sale_create"), data).status_code, 403)
        self.assertEqual(Sale.objects.count(), 0)
        data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        response = client.post(reverse("commerce:sale_create"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Sale.objects.get().items.get().product_id, self.product.pk)

    def test_product_search_never_returns_private_member_fields(self):
        response = self.client.get(reverse("club:search_suggestions"), {"q": "Searchable"})
        for private_value in [self.member.name, self.member.email, self.member.phone]:
            self.assertNotContains(response, private_value)
        response = self.client.get(reverse("club:search_suggestions"), {"q": self.member.name})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestions"], [])

    def test_concierge_commerce_chip_returns_its_commerce_answer(self):
        response = self.client.get(reverse("club:help_bot_faq"), {"q": "commerce"})
        self.assertEqual(response.status_code, 200)
        answer = response.json()["faqs"][0]
        self.assertEqual(answer["id"], "commerce")
        self.assertEqual(answer["action_url"], reverse("commerce:index"))

    def test_expanded_plan_tiers_use_configured_discounts(self):
        for tier in ["platinum", "corporate", "weekend", "custom"]:
            with self.subTest(tier=tier):
                plan = MembershipPlan.objects.create(
                    tier=tier, name=f"{tier} test", shop_discount_percent=Decimal("12.00"),
                )
                member = Member.objects.create(name=f"{tier} buyer", plan=plan)
                sale = complete_sale(create_sale(
                    quantities={self.product.pk: 1}, payment_method="cash", member_id=member.pk,
                ).pk)
                self.assertEqual(sale.discount, Decimal("179.94"))
                self.assertEqual(sale.total, Decimal("1319.56"))
                cancel_sale(sale.pk)

    def test_plan_management_edit_changes_new_sales_only(self):
        before = complete_sale(create_sale(
            quantities={self.product.pk: 1}, payment_method="cash", member_id=self.member.pk,
        ).pk)
        form = MembershipPlanForm({
            "tier": "silver", "name": "Updated Silver", "membership_fee": "3000.00",
            "court_hourly_rate": "200.00", "shop_discount_percent": "20.00",
            "bar_discount_percent": "7.00", "active": "on",
        }, instance=self.plan)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        after = complete_sale(create_sale(
            quantities={self.product.pk: 1}, payment_method="cash", member_id=self.member.pk,
        ).pk)
        before.refresh_from_db()
        self.assertEqual(before.discount, Decimal("149.95"))
        self.assertEqual(after.discount, Decimal("299.90"))
        self.assertEqual(complete_sale(before.pk).discount, Decimal("149.95"))
