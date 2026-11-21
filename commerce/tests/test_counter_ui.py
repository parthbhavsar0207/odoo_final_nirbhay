"""The current frontend app must render the tested guest-counter backend."""

from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.db import connection
from django.template.loader import get_template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from commerce.models import Product, Sale
from commerce.services import cancel_sale, complete_sale, create_guest_sale


class FormMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current_form = None
        self.links = []
        self.products = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-product-id" in attrs:
            self.products.append(attrs)
        if tag == "form":
            self.current_form = {"attrs": attrs, "controls": []}
            self.forms.append(self.current_form)
        elif tag in ("input", "select", "textarea", "button") and self.current_form is not None:
            self.current_form["controls"].append(attrs)
        elif tag == "a":
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag == "form":
            self.current_form = None


class FrontendOriginTests(SimpleTestCase):
    def test_shared_base_is_loaded_from_frontend_app(self):
        self.assertEqual(
            Path(get_template("base.html").origin.name).resolve(),
            (settings.BASE_DIR / "frontend/templates/base.html").resolve(),
        )

    def test_counter_template_is_loaded_from_frontend_app(self):
        self.assertEqual(
            Path(get_template("commerce/index.html").origin.name).resolve(),
            (settings.BASE_DIR / "frontend/templates/commerce/index.html").resolve(),
        )

    def test_shared_and_counter_assets_resolve_only_under_frontend(self):
        expected_root = (settings.BASE_DIR / "frontend/static").resolve()
        for relative in ["css/style.css", "js/main.js", "css/commerce.css", "js/commerce.js"]:
            with self.subTest(asset=relative):
                matches = finders.find(relative, all=True)
                self.assertTrue(matches, f"Missing active frontend asset: {relative}")
                self.assertTrue(all(Path(match).resolve().is_relative_to(expected_root) for match in matches))

    def test_old_frontend_directories_are_not_restored_or_configured(self):
        self.assertFalse((settings.BASE_DIR / "templates").exists())
        self.assertFalse((settings.BASE_DIR / "static").exists())
        self.assertNotIn(settings.BASE_DIR / "templates", settings.TEMPLATES[0]["DIRS"])
        self.assertNotIn(settings.BASE_DIR / "static", settings.STATICFILES_DIRS)


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL counter sales")
class GuestCounterRenderedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Tennis ball", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )
        cls.bar_product = Product.objects.create(
            name="Refreshment", category="bar", price=Decimal("1.20"), stock_quantity=5,
        )
        cls.inactive_product = Product.objects.create(
            name="Retired racket", category="shop", price=Decimal("50.00"),
            stock_quantity=2, is_active=False,
        )

    def draft(self, quantity=2):
        return create_guest_sale(
            quantities={self.product.pk: quantity}, payment_method=Sale.PaymentMethod.CASH,
        )

    def detail(self, sale):
        return self.client.get(reverse("commerce:sale_detail", args=[sale.pk]))

    def markup(self, response):
        return FormMarkup(response.content.decode())

    def form_for(self, response, route, args=None):
        action = reverse(route, args=args)
        matches = [form for form in self.markup(response).forms if form["attrs"].get("action") == action]
        self.assertEqual(len(matches), 1, f"Expected one rendered form for {action}")
        self.assertEqual(matches[0]["attrs"].get("method", "get").lower(), "post")
        return matches[0]

    def assert_form_csrf(self, form):
        tokens = [control for control in form["controls"] if control.get("name") == "csrfmiddlewaretoken"]
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].get("type"), "hidden")
        self.assertTrue(tokens[0].get("value"))

    def test_navigation_and_new_sale_open_working_counter(self):
        response = self.client.get(reverse("commerce:guest_counter"))
        counter_url = reverse("commerce:guest_counter")
        links = self.markup(response).links
        self.assertTrue(any(link.get("href") == counter_url for link in links))
        self.assertTrue(any(link.get("href") == counter_url + "#guest-sale-form" for link in links))
        self.assertContains(response, "Shop &amp; Bar POS")
        self.assertContains(response, "New Sale")

    def test_existing_catalog_entry_points_use_real_counter_without_login(self):
        for name in ["commerce:index", "commerce:shop"]:
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, "Tennis ball")
                self.assertTemplateUsed(response, "commerce/index.html")

    def test_product_admin_still_requires_login(self):
        admin_url = reverse("admin:commerce_product_changelist")
        response = self.client.get(admin_url)
        self.assertRedirects(
            response, reverse("admin:login") + "?next=" + admin_url,
            fetch_redirect_response=False,
        )

    def test_catalog_cards_show_real_products_and_enabled_sell_links(self):
        response = self.client.get(reverse("commerce:guest_counter"))
        self.assertContains(response, "Tennis ball")
        self.assertContains(response, "Refreshment")
        self.assertNotContains(response, "Retired racket")
        markup = self.markup(response)
        self.assertEqual({entry["data-product-id"] for entry in markup.products}, {
            str(self.product.pk), str(self.bar_product.pk),
        })
        sell_links = [link for link in markup.links if "data-sell-product" in link]
        self.assertEqual({link["data-sell-product"] for link in sell_links}, {
            str(self.product.pk), str(self.bar_product.pk),
        })
        self.assertTrue(all(link.get("href") == reverse("commerce:guest_counter") + "#guest-sale-form" for link in sell_links))

    def test_empty_catalog_has_no_fabricated_products_prices_or_disabled_sale_controls(self):
        Product.objects.update(is_active=False)
        response = self.client.get(reverse("commerce:guest_counter"))
        self.assertEqual(self.markup(response).products, [])
        self.assertEqual([link for link in self.markup(response).links if "data-sell-product" in link], [])
        for fabricated in ["Wilson Blade", "Heritage Polo", "22,500.00", "Design System Catalog Preview Wireframe", "PRD-LIVE"]:
            with self.subTest(fabricated=fabricated):
                self.assertNotContains(response, fabricated)
        self.assertNotContains(response, "disabled")

    def test_create_form_renders_actual_fields_named_target_and_csrf(self):
        response = self.client.get(reverse("commerce:guest_counter"))
        form = self.form_for(response, "commerce:sale_create")
        self.assert_form_csrf(form)
        names = {control.get("name") for control in form["controls"] if control.get("name")}
        self.assertEqual(names, {"product", "quantity", "payment_method", "csrfmiddlewaretoken"})

    def test_invalid_field_errors_are_visible_and_entered_values_retained(self):
        response = self.client.post(reverse("commerce:sale_create"), {
            "product": str(self.product.pk), "quantity": "0", "payment_method": "cash",
        })
        self.assertEqual(response.status_code, 400)
        for error in response.context["form"].errors["quantity"]:
            self.assertContains(response, error, status_code=400)
        self.assertContains(response, 'value="0"', status_code=400)
        self.assertEqual(Sale.objects.count(), 0)

    def test_creation_nonfield_error_is_visible_and_escaped(self):
        error = "Unavailable <script>alert('stock')</script>"
        with patch("commerce.views.create_guest_sale", side_effect=ValidationError(error)):
            response = self.client.post(reverse("commerce:sale_create"), {
                "product": str(self.product.pk), "quantity": "2", "payment_method": "cash",
            })
        self.assertContains(response, "Unavailable &lt;script&gt;", status_code=400)
        self.assertNotContains(response, "<script>alert('stock')</script>", status_code=400)

    def test_draft_shows_pending_feedback_and_two_csrf_action_forms(self):
        sale = self.draft()
        response = self.detail(sale)
        self.assertContains(response, "Draft")
        self.assertContains(response, "Draft created. Stock changes only when you complete the sale.")
        for route in ["commerce:sale_complete", "commerce:sale_cancel"]:
            self.assert_form_csrf(self.form_for(response, route, [sale.pk]))

    def test_completed_sale_shows_saved_snapshots_and_only_cancel_action(self):
        sale = complete_sale(self.draft().pk)
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("99.00"))
        response = self.detail(sale)
        self.assertContains(response, "Completed")
        self.assertContains(response, "Sale completed. Inventory has been deducted.")
        self.assertContains(response, "12.50")
        self.assertContains(response, "25.00")
        self.assert_form_csrf(self.form_for(response, "commerce:sale_cancel", [sale.pk]))
        complete_target = reverse("commerce:sale_complete", args=[sale.pk])
        self.assertFalse(any(form["attrs"].get("action") == complete_target for form in self.markup(response).forms))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

    def test_cancelled_sale_keeps_snapshots_without_state_change_forms(self):
        sale = cancel_sale(complete_sale(self.draft().pk).pk)
        response = self.detail(sale)
        self.assertContains(response, "Cancelled")
        self.assertContains(response, "Sale cancelled. Any deducted inventory has been restored.")
        self.assertContains(response, "25.00")
        targets = {reverse("commerce:sale_complete", args=[sale.pk]), reverse("commerce:sale_cancel", args=[sale.pk])}
        self.assertFalse(any(form["attrs"].get("action") in targets for form in self.markup(response).forms))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_insufficient_stock_feedback_is_visible_and_draft_can_be_cancelled(self):
        sale = self.draft(quantity=11)
        response = self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        self.assertContains(response, "only 10 available", status_code=409)
        self.assert_form_csrf(self.form_for(response, "commerce:sale_cancel", [sale.pk]))
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(self.product.stock_quantity, 10)

    def test_action_error_is_escaped(self):
        sale = self.draft()
        error = "Cannot complete <script>alert('state')</script>"
        with patch("commerce.views.complete_sale", side_effect=ValidationError(error)):
            response = self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        self.assertContains(response, "Cannot complete &lt;script&gt;", status_code=409)
        self.assertNotContains(response, "<script>alert('state')</script>", status_code=409)
