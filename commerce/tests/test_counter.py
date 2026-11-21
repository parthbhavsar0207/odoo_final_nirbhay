"""Guest-counter HTTP/form tests against the real PostgreSQL commerce models."""

from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection
from django.test import Client, TestCase
from django.urls import reverse

from commerce.counter_forms import GuestSaleForm
from commerce.models import Product, Sale
from commerce.services import create_guest_sale


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL counter sales")
class GuestCounterFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Tennis ball", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )
        cls.inactive = Product.objects.create(
            name="Retired item", category="bar", price=Decimal("1.00"),
            stock_quantity=2, is_active=False,
        )

    def form(self, **overrides):
        data = {
            "product": str(self.product.pk),
            "quantity": "2",
            "payment_method": "cash",
        }
        data.update(overrides)
        return GuestSaleForm(data=data)

    def test_form_parses_existing_product_quantity_and_payment(self):
        form = self.form(payment_method="UPI")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["product"], self.product)
        self.assertEqual(form.cleaned_data["quantity"], 2)
        self.assertEqual(form.cleaned_data["payment_method"], Sale.PaymentMethod.UPI)

    def test_form_exposes_only_product_quantity_and_payment(self):
        self.assertEqual(set(GuestSaleForm().fields), {"product", "quantity", "payment_method"})

    def test_unknown_and_inactive_product_ids_are_invalid(self):
        missing_id = max(self.product.pk, self.inactive.pk) + 100
        for value in [str(missing_id), str(self.inactive.pk), "invalid", ""]:
            with self.subTest(product=value):
                form = self.form(product=value)
                self.assertFalse(form.is_valid())
                self.assertIn("product", form.errors)

    def test_fractional_zero_negative_and_oversized_quantities_are_invalid(self):
        for value in ["1.5", "0", "-1", "2147483648", "NaN", ""]:
            with self.subTest(quantity=value):
                form = self.form(quantity=value)
                self.assertFalse(form.is_valid())
                self.assertIn("quantity", form.errors)

    def test_unknown_payment_method_is_invalid(self):
        form = self.form(payment_method="upi")
        self.assertFalse(form.is_valid())
        self.assertIn("payment_method", form.errors)

    def test_untrusted_amounts_and_member_fields_are_not_cleaned(self):
        form = self.form(price="0.01", discount="100", total="0.00", member="123")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(set(form.cleaned_data), {"product", "quantity", "payment_method"})


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL counter sales")
class GuestCounterViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.staff = user_model.objects.create_user(username="counter-staff", is_staff=True)
        cls.nonstaff = user_model.objects.create_user(username="counter-customer")
        cls.inactive_staff = user_model.objects.create_user(
            username="counter-inactive", is_staff=True, is_active=False,
        )
        cls.product = Product.objects.create(
            name="Tennis ball", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )
        cls.inactive_product = Product.objects.create(
            name="Retired item", category="bar", price=Decimal("1.00"),
            stock_quantity=2, is_active=False,
        )

    def draft(self, quantity=2):
        return create_guest_sale(
            quantities={self.product.pk: quantity}, payment_method=Sale.PaymentMethod.CASH,
        )

    def create_data(self, **overrides):
        values = {
            "product": str(self.product.pk), "quantity": "2", "payment_method": "cash",
        }
        values.update(overrides)
        return values

    def test_all_counter_operations_work_without_staff_authentication(self):
        for user in [None, self.nonstaff, self.inactive_staff, self.staff]:
            with self.subTest(user=user):
                client = Client()
                if user is not None:
                    client.force_login(user)
                response = client.get(reverse("commerce:guest_counter"))
                self.assertEqual(response.status_code, 200)
                response = client.post(reverse("commerce:sale_create"), self.create_data())
                sale = Sale.objects.latest("pk")
                detail_url = reverse("commerce:sale_detail", args=[sale.pk])
                self.assertRedirects(response, detail_url, fetch_redirect_response=False)
                self.assertEqual(client.get(detail_url).status_code, 200)
                response = client.post(reverse("commerce:sale_complete", args=[sale.pk]))
                self.assertRedirects(response, detail_url, fetch_redirect_response=False)
                self.product.refresh_from_db()
                self.assertEqual(self.product.stock_quantity, 8)
                response = client.post(reverse("commerce:sale_cancel", args=[sale.pk]))
                self.assertRedirects(response, detail_url, fetch_redirect_response=False)
                sale.refresh_from_db()
                self.product.refresh_from_db()
                self.assertEqual(sale.status, Sale.Status.CANCELLED)
                self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(Sale.objects.count(), 4)

    def test_counter_get_reuses_existing_template_and_supplies_form_context(self):
        response = self.client.get(reverse("commerce:guest_counter"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "commerce/index.html")
        self.assertIsInstance(response.context["form"], GuestSaleForm)
        self.assertEqual(list(response.context["products"]), [self.product])
        self.assertIsNone(response.context["sale"])
        self.assertIsNone(response.context["error_message"])
        self.assertEqual(list(response.context["sale_items"]), [])

    def test_display_routes_allow_head_and_reject_post(self):
        sale = self.draft()
        for url in [reverse("commerce:guest_counter"), reverse("commerce:sale_detail", args=[sale.pk])]:
            with self.subTest(url=url):
                self.assertEqual(self.client.head(url).status_code, 200)
                self.assertEqual(self.client.post(url, {}).status_code, 405)

    def test_state_change_routes_reject_non_post_methods(self):
        sale = self.draft()
        for name, args in [
            ("commerce:sale_create", []),
            ("commerce:sale_complete", [sale.pk]),
            ("commerce:sale_cancel", [sale.pk]),
        ]:
            for method in ["get", "head", "put", "delete"]:
                with self.subTest(name=name, method=method):
                    response = getattr(self.client, method)(reverse(name, args=args))
                    self.assertEqual(response.status_code, 405)
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(self.product.stock_quantity, 10)

    def test_valid_post_creates_draft_and_redirects_to_named_detail(self):
        response = self.client.post(
            reverse("commerce:sale_create"),
            self.create_data(payment_method="UPI", next="https://example.com/"),
        )
        sale = Sale.objects.get()
        self.assertRedirects(response, reverse("commerce:sale_detail", args=[sale.pk]), fetch_redirect_response=False)
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(sale.payment_method, Sale.PaymentMethod.UPI)
        self.assertEqual(sale.items.get().quantity, 2)
        self.assertEqual(sale.total, Decimal("0.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_repeated_creation_is_not_request_idempotent(self):
        url = reverse("commerce:sale_create")
        for _ in range(2):
            self.assertEqual(self.client.post(url, self.create_data()).status_code, 302)
        self.assertEqual(Sale.objects.filter(status=Sale.Status.DRAFT).count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_invalid_form_returns_bound_errors_without_creating_sale(self):
        response = self.client.post(
            reverse("commerce:sale_create"), self.create_data(quantity="1.5", payment_method="bitcoin"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context["form"].is_bound)
        self.assertIn("quantity", response.context["form"].errors)
        self.assertIn("payment_method", response.context["form"].errors)
        self.assertEqual(Sale.objects.count(), 0)

    def test_invalid_product_submission_returns_controlled_error(self):
        for product_id in [self.inactive_product.pk, self.inactive_product.pk + 100]:
            with self.subTest(product_id=product_id):
                response = self.client.post(
                    reverse("commerce:sale_create"), self.create_data(product=str(product_id)),
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("product", response.context["form"].errors)
        self.assertEqual(Sale.objects.count(), 0)

    def test_create_service_validation_error_is_returned_as_form_error(self):
        with patch("commerce.views.create_guest_sale", side_effect=ValidationError("Product is no longer active.")):
            response = self.client.post(reverse("commerce:sale_create"), self.create_data())
        self.assertEqual(response.status_code, 400)
        self.assertIn("Product is no longer active.", response.context["form"].non_field_errors())
        self.assertEqual(Sale.objects.count(), 0)

    def test_complete_post_uses_product_price_and_deducts_stock(self):
        sale = self.draft()
        response = self.client.post(
            reverse("commerce:sale_complete", args=[sale.pk]),
            {"price": "0.01", "discount": "99", "quantity": "100", "next": "https://example.com/"},
        )
        self.assertRedirects(response, reverse("commerce:sale_detail", args=[sale.pk]), fetch_redirect_response=False)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.total, Decimal("25.00"))
        self.assertEqual(sale.items.get().quantity, 2)

    def test_repeated_completion_does_not_deduct_stock_twice(self):
        sale = self.draft()
        url = reverse("commerce:sale_complete", args=[sale.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

    def test_cancel_completed_sale_restores_stock_once(self):
        sale = self.draft()
        self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        url = reverse("commerce:sale_cancel", args=[sale.pk])
        for _ in range(2):
            response = self.client.post(url)
            self.assertRedirects(response, reverse("commerce:sale_detail", args=[sale.pk]), fetch_redirect_response=False)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.CANCELLED)

    def test_cancel_draft_does_not_restore_stock(self):
        sale = self.draft()
        url = reverse("commerce:sale_cancel", args=[sale.pk])
        self.client.post(url)
        self.client.post(url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_insufficient_stock_returns_conflict_with_unchanged_draft(self):
        sale = self.draft(quantity=11)
        response = self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertIn("only 10 available", response.context["error_message"])
        self.assertEqual(response.context["sale"].pk, sale.pk)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.DRAFT)

    def test_cancelled_sale_completion_returns_controlled_state_conflict(self):
        sale = self.draft()
        self.client.post(reverse("commerce:sale_cancel", args=[sale.pk]))
        response = self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertIn("Only draft sales", response.context["error_message"])

    def test_missing_sale_ids_return_404_for_display_and_mutation(self):
        for name, method in [
            ("commerce:sale_detail", "get"),
            ("commerce:sale_complete", "post"),
            ("commerce:sale_cancel", "post"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(getattr(self.client, method)(reverse(name, args=[999999])).status_code, 404)

    def test_detail_displays_snapshots_without_repricing_or_stock_changes(self):
        sale = self.draft()
        self.client.post(reverse("commerce:sale_complete", args=[sale.pk]))
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("99.00"))
        response = self.client.get(reverse("commerce:sale_detail", args=[sale.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "commerce/index.html")
        self.assertEqual(response.context["sale"].total, Decimal("25.00"))
        self.assertEqual(list(response.context["sale_items"])[0].unit_price, Decimal("12.50"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

    def test_service_database_error_returns_generic_unavailable_response(self):
        sale = self.draft()
        for target, url, data in [
            ("commerce.views.create_guest_sale", reverse("commerce:sale_create"), self.create_data()),
            ("commerce.views.complete_sale", reverse("commerce:sale_complete", args=[sale.pk]), {}),
            ("commerce.views.cancel_sale", reverse("commerce:sale_cancel", args=[sale.pk]), {}),
        ]:
            with self.subTest(target=target):
                with self.assertLogs("commerce.views", level="ERROR"), patch(
                    target, side_effect=DatabaseError("injected database fault"),
                ):
                    response = self.client.post(url, data)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(b"injected database fault", response.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL counter sales")
class GuestCounterCsrfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Tennis ball", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_all_state_changes_reject_requests_without_csrf_tokens(self):
        sale = create_guest_sale(quantities={self.product.pk: 2}, payment_method="cash")
        for url in [
            reverse("commerce:sale_create"),
            reverse("commerce:sale_complete", args=[sale.pk]),
            reverse("commerce:sale_cancel", args=[sale.pk]),
        ]:
            with self.subTest(url=url):
                response = self.client.post(url, {
                    "product": str(self.product.pk), "quantity": "2", "payment_method": "cash",
                })
                self.assertEqual(response.status_code, 403)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertEqual(Sale.objects.count(), 1)

    def test_counter_get_supplies_csrf_cookie_for_pratik_form(self):
        response = self.client.get(reverse("commerce:guest_counter"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", self.client.cookies)

    def test_valid_csrf_token_allows_create_complete_and_cancel(self):
        self.client.get(reverse("commerce:guest_counter"))
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(reverse("commerce:sale_create"), {
            "product": str(self.product.pk), "quantity": "2", "payment_method": "cash",
            "csrfmiddlewaretoken": token,
        })
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        for name in ["commerce:sale_complete", "commerce:sale_cancel"]:
            with self.subTest(name=name):
                response = self.client.post(
                    reverse(name, args=[sale.pk]), {}, HTTP_X_CSRFTOKEN=token,
                )
                self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(sale.status, Sale.Status.CANCELLED)
