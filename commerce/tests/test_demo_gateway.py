"""Simulated checkout uses real PostgreSQL transactions, never real payments."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from club.models import Booking, Court, Member, MembershipPlan
from commerce.demo_gateway import simulate_payment
from commerce.models import Product, Sale
from commerce.payment_views import CHECKOUT_MAX_AGE, SALT
from commerce.services import cancel_sale, complete_sale, create_sale, quote_sale


class GatewayFixtures:
    def draft_sale(self, *, payment_method=Sale.PaymentMethod.UPI, quantity=2, member=None):
        return create_sale(
            quantities={self.product.pk: quantity}, payment_method=payment_method,
            member_id=member.pk if member else None,
        )

    def pending_booking(self, *, payment_method=Booking.PaymentMethod.UPI):
        start = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return Booking.objects.create(
            court=self.court, walkin_name="Demo payment guest", start_datetime=start,
            status="confirmed", payment_method=payment_method,
            payment_status=Booking.PaymentStatus.PENDING,
        )

    def pay(self, target, *, kind="sale", amount=None, outcome="success"):
        if amount is None:
            amount = quote_sale(target.pk) if kind == "sale" else target.price
        return simulate_payment(
            kind=kind, pk=target.pk, amount=amount,
            payment_method=target.payment_method, outcome=outcome,
        )

    def assert_draft_unchanged(self, sale, *, stock=10):
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, stock)
        self.assertEqual(sale.status, Sale.Status.DRAFT)
        self.assertFalse(sale.payment_is_simulated)
        self.assertEqual(sale.demo_payment_reference, "")
        self.assertEqual(sale.total, Decimal("0.00"))
        self.assertEqual(sale.items.get().unit_price, Decimal("0.00"))


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL checkout transactions")
class DemoGatewayServiceTests(GatewayFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Demo shop product", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )
        cls.court = Court.objects.create(name="Demo payment court", hourly_rate=Decimal("500.00"))

    def test_decimal_quote_never_writes_snapshots_or_inventory(self):
        sale = self.draft_sale()
        self.assertEqual(quote_sale(sale.pk), Decimal("25.00"))
        self.assert_draft_unchanged(sale)

    def test_success_and_repeated_success_use_same_reference_and_deduct_once(self):
        sale = self.draft_sale()
        first, result = self.pay(sale)
        retried, retry_result = self.pay(sale, amount=Decimal("25.00"))
        self.assertEqual((result, retry_result), ("success", "already_successful"))
        self.assertTrue(first.payment_is_simulated)
        self.assertRegex(first.demo_payment_reference, r"^DEMO-[a-f0-9]{32}$")
        self.assertEqual(first.demo_payment_reference, retried.demo_payment_reference)
        self.assertEqual(retried.total, Decimal("25.00"))
        self.assertEqual(retried.items.get().unit_price, Decimal("12.50"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

    def test_failure_and_payment_cancel_leave_sale_and_inventory_unchanged(self):
        sale = self.draft_sale()
        for outcome in ["failure", "cancel"]:
            with self.subTest(outcome=outcome):
                _, result = self.pay(sale, outcome=outcome)
                self.assertEqual(result, outcome)
                self.assert_draft_unchanged(sale)

    def test_quote_and_completion_use_shared_member_discount_and_decimal_rounding(self):
        plan = MembershipPlan.objects.create(
            tier="silver", name="Demo Silver", shop_discount_percent=Decimal("10.00"),
            bar_discount_percent=Decimal("5.00"),
        )
        member = Member.objects.create(name="Demo member", plan=plan)
        bar = Product.objects.create(
            name="Demo bar product", category="bar", price=Decimal("1.20"), stock_quantity=10,
        )
        sale = create_sale(
            quantities={self.product.pk: 2, bar.pk: 3}, payment_method="card", member_id=member.pk,
        )
        self.assertEqual(quote_sale(sale.pk), Decimal("25.92"))
        paid, result = self.pay(sale)
        self.assertEqual(result, "success")
        self.assertEqual((paid.subtotal, paid.discount, paid.total),
                         (Decimal("28.60"), Decimal("2.68"), Decimal("25.92")))
        self.assertEqual(paid.items.get(product=bar).discount, Decimal("0.18"))

    def test_product_price_and_plan_drift_reject_stale_checkout_without_writes(self):
        plan = MembershipPlan.objects.create(
            tier="silver", name="Demo Silver", shop_discount_percent=Decimal("10.00"),
        )
        member = Member.objects.create(name="Demo member", plan=plan)
        sale = self.draft_sale(member=member)
        amount = quote_sale(sale.pk)
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("13.00"))
        with self.assertRaises(ValidationError) as error:
            self.pay(sale, amount=amount)
        self.assertEqual(error.exception.code, "stale_checkout")
        self.assert_draft_unchanged(sale)
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("12.50"))
        MembershipPlan.objects.filter(pk=plan.pk).update(shop_discount_percent=Decimal("20.00"))
        with self.assertRaises(ValidationError) as error:
            self.pay(sale, amount=amount)
        self.assertEqual(error.exception.code, "stale_checkout")
        self.assert_draft_unchanged(sale)

    def test_stock_exhausted_after_quote_leaves_draft_unpaid(self):
        sale = self.draft_sale()
        amount = quote_sale(sale.pk)
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=1)
        with self.assertRaises(ValidationError) as error:
            self.pay(sale, amount=amount)
        self.assertEqual(error.exception.code, "insufficient_stock")
        self.assert_draft_unchanged(sale, stock=1)

    def test_failure_saving_demo_reference_rolls_back_completion_and_stock(self):
        sale = self.draft_sale()
        original_save = Sale.save

        def fail_reference_save(instance, *args, **kwargs):
            if "payment_is_simulated" in kwargs.get("update_fields", []):
                raise RuntimeError("Injected demo-reference write failure")
            return original_save(instance, *args, **kwargs)

        with patch.object(Sale, "save", autospec=True, side_effect=fail_reference_save):
            with self.assertRaises(RuntimeError):
                self.pay(sale)
        self.assert_draft_unchanged(sale)

    def test_manually_completed_or_cancelled_sale_cannot_be_relabelled_simulated(self):
        completed = complete_sale(self.draft_sale().pk)
        with self.assertRaises(ValidationError) as error:
            self.pay(completed, amount=completed.total)
        self.assertEqual(error.exception.code, "already_completed")
        completed.refresh_from_db()
        self.assertFalse(completed.payment_is_simulated)
        cancelled = cancel_sale(self.draft_sale().pk)
        with self.assertRaises(ValidationError) as error:
            self.pay(cancelled, amount=Decimal("25.00"))
        self.assertEqual(error.exception.code, "invalid_sale_state")

    def test_completed_simulated_cancellation_restores_stock_once_and_keeps_reference(self):
        sale, _ = self.pay(self.draft_sale())
        reference = sale.demo_payment_reference
        cancel_sale(sale.pk)
        cancel_sale(sale.pk)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual((self.product.stock_quantity, sale.status), (10, Sale.Status.CANCELLED))
        self.assertEqual(sale.demo_payment_reference, reference)

    def test_invalid_amount_outcome_or_cash_method_are_rejected(self):
        sale = self.draft_sale()
        for amount in ["25.00", Decimal("NaN"), Decimal("Infinity"), Decimal("-1.00")]:
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.pay(sale, amount=amount)
        with self.assertRaises(ValidationError):
            self.pay(sale, outcome="approved")
        cash_sale = self.draft_sale(payment_method="cash")
        with self.assertRaises(ValidationError) as error:
            self.pay(cash_sale)
        self.assertEqual(error.exception.code, "invalid_payment_method")
        self.assert_draft_unchanged(sale)

    def test_booking_success_and_retry_preserve_snapshot_and_reference(self):
        booking = self.pending_booking()
        Court.objects.filter(pk=self.court.pk).update(hourly_rate=Decimal("999.00"))
        paid, result = self.pay(booking, kind="booking")
        retried, retry_result = self.pay(booking, kind="booking")
        self.assertEqual((result, retry_result), ("success", "already_successful"))
        self.assertEqual((paid.price, paid.payment_status, paid.status),
                         (Decimal("500.00"), Booking.PaymentStatus.PAID, "confirmed"))
        self.assertTrue(paid.payment_is_simulated)
        self.assertEqual(paid.demo_payment_reference, retried.demo_payment_reference)
        self.assertRegex(paid.demo_payment_reference, r"^DEMO-[a-f0-9]{32}$")

    def test_booking_failure_or_payment_cancel_preserves_pending_reservation(self):
        booking = self.pending_booking()
        for outcome in ["failure", "cancel"]:
            with self.subTest(outcome=outcome):
                _, result = self.pay(booking, kind="booking", outcome=outcome)
                booking.refresh_from_db()
                self.assertEqual(result, outcome)
                self.assertEqual((booking.status, booking.payment_status), ("confirmed", "pending"))
                self.assertFalse(booking.payment_is_simulated)
                self.assertEqual(booking.demo_payment_reference, "")

    def test_paid_cancelled_free_or_cash_booking_cannot_enter_simulator(self):
        booking = self.pending_booking()
        states = [
            ({"payment_status": "paid"}, "already_paid"),
            ({"status": "cancelled"}, "invalid_booking_state"),
            ({"price": Decimal("0.00")}, "invalid_payment_state"),
            ({"payment_method": "cash"}, "invalid_payment_method"),
        ]
        baseline = {"status": "confirmed", "payment_status": "pending", "price": Decimal("500.00"), "payment_method": "upi"}
        for changes, code in states:
            with self.subTest(changes=changes):
                Booking.objects.filter(pk=booking.pk).update(**{**baseline, **changes})
                booking.refresh_from_db()
                with self.assertRaises(ValidationError) as error:
                    self.pay(booking, kind="booking")
                self.assertEqual(error.exception.code, code)
                booking.refresh_from_db()
                self.assertFalse(booking.payment_is_simulated)


@override_settings(DEMO_PAYMENT_GATEWAY_ENABLED=True)
@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL checkout views")
class DemoGatewayViewTests(GatewayFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Checkout product", category="shop", price=Decimal("12.50"), stock_quantity=10,
        )
        cls.court = Court.objects.create(name="Checkout court", hourly_rate=Decimal("500.00"))

    def checkout(self, target, *, kind="sale", client=None):
        client = client or self.client
        response = client.get(reverse("commerce:demo_payment", args=[kind, target.pk]))
        self.assertEqual(response.status_code, 200)
        return response.context["checkout_token"]

    def submit(self, target, token, *, kind="sale", client=None, outcome="success", **extra):
        client = client or self.client
        return client.post(reverse("commerce:demo_payment_submit", args=[kind, target.pk]), {
            "checkout_token": token, "outcome": outcome, **extra,
        })

    def test_checkout_get_is_read_only_and_clearly_simulated_without_login(self):
        sale = self.draft_sale()
        response = self.client.get(reverse("commerce:demo_payment", args=["sale", sale.pk]))
        self.assertTemplateUsed(response, "commerce/demo_payment.html")
        self.assertContains(response, "Demo checkout")
        self.assertContains(response, "No money is charged or transferred")
        self.assertContains(response, "Do not enter card details")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertEqual(response.context["amount"], Decimal("25.00"))
        self.assertTrue(response.context["payable"])
        self.assertTrue(response.context["checkout_token"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assert_draft_unchanged(sale)

    def test_success_post_ignores_browser_amount_and_retry_keeps_stock_and_reference(self):
        sale = self.draft_sale()
        token = self.checkout(sale)
        response = self.submit(sale, token, amount="0.01", payment_method="cash", next="https://example.com/")
        detail_url = reverse("commerce:sale_detail", args=[sale.pk])
        self.assertRedirects(response, detail_url, fetch_redirect_response=False)
        sale.refresh_from_db()
        reference = sale.demo_payment_reference
        self.assertEqual(sale.total, Decimal("25.00"))
        self.assertRedirects(self.submit(sale, token), detail_url, fetch_redirect_response=False)
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(sale.demo_payment_reference, reference)
        self.assertEqual(self.product.stock_quantity, 8)
        receipt = self.client.get(reverse("commerce:sale_receipt", args=[sale.pk]))
        self.assertContains(receipt, reference)
        self.assertContains(receipt, "No money was charged or transferred")

    def test_failure_and_cancel_feedback_leave_sale_available_for_retry(self):
        sale = self.draft_sale()
        token = self.checkout(sale)
        failure = self.submit(sale, token, outcome="failure")
        self.assertContains(failure, "Simulated payment failed")
        self.assertTrue(failure.context["payable"])
        cancelled = self.submit(sale, token, outcome="cancel")
        self.assertRedirects(cancelled, reverse("commerce:sale_detail", args=[sale.pk]), fetch_redirect_response=False)
        self.assert_draft_unchanged(sale)

    def test_tampered_expired_target_mismatched_and_cross_session_tokens_are_rejected(self):
        sale = self.draft_sale()
        token = self.checkout(sale)
        payload = signing.loads(token, salt=SALT)
        other = self.draft_sale()
        mismatched = signing.dumps({**payload, "pk": other.pk}, salt=SALT)
        for invalid in [token + "tampered", mismatched]:
            with self.subTest(token=invalid):
                response = self.submit(sale, invalid)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "expired or is invalid", status_code=400)
        other_client = Client()
        self.checkout(sale, client=other_client)
        self.assertEqual(self.submit(sale, token, client=other_client).status_code, 400)
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + CHECKOUT_MAX_AGE + 60):
            self.assertEqual(self.submit(sale, token).status_code, 400)
        self.assert_draft_unchanged(sale)

    def test_stale_price_and_payment_method_tokens_return_controlled_conflict(self):
        sale = self.draft_sale()
        token = self.checkout(sale)
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("13.00"))
        response = self.submit(sale, token)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Price or benefits changed", status_code=409)
        self.assertEqual(response.context["amount"], Decimal("26.00"))
        self.assert_draft_unchanged(sale)
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("12.50"))
        Sale.objects.filter(pk=sale.pk).update(payment_method="card")
        response = self.submit(sale, token)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Payment method changed", status_code=409)
        self.assert_draft_unchanged(sale)

    def test_insufficient_stock_after_checkout_is_controlled_conflict(self):
        sale = self.draft_sale()
        token = self.checkout(sale)
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=1)
        response = self.submit(sale, token)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "only 1 available", status_code=409)
        self.assertFalse(response.context["payable"])
        self.assert_draft_unchanged(sale, stock=1)

    def test_invalid_outcome_or_missing_token_returns_400_without_business_mutation(self):
        sale = self.draft_sale()
        token = self.checkout(sale)
        self.assertEqual(self.submit(sale, token, outcome="approved").status_code, 400)
        self.assertEqual(self.submit(sale, "").status_code, 400)
        self.assert_draft_unchanged(sale)

    def test_checkout_methods_unknown_targets_and_disabled_feature(self):
        sale = self.draft_sale()
        display = reverse("commerce:demo_payment", args=["sale", sale.pk])
        submit = reverse("commerce:demo_payment_submit", args=["sale", sale.pk])
        self.assertEqual(self.client.head(display).status_code, 200)
        self.assertEqual(self.client.post(display).status_code, 405)
        for method in ["get", "head", "put", "delete"]:
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(submit).status_code, 405)
        for kind, pk in [("unknown", sale.pk), ("sale", sale.pk + 100000), ("booking", 100000)]:
            with self.subTest(kind=kind):
                self.assertEqual(self.client.get(reverse("commerce:demo_payment", args=[kind, pk])).status_code, 404)
        with override_settings(DEMO_PAYMENT_GATEWAY_ENABLED=False):
            self.assertEqual(self.client.get(display).status_code, 404)
            self.assertEqual(self.client.post(submit, {"outcome": "success"}).status_code, 404)
        self.assert_draft_unchanged(sale)

    def test_submit_requires_csrf_and_valid_csrf_allows_completion(self):
        sale = self.draft_sale()
        client = Client(enforce_csrf_checks=True)
        token = self.checkout(sale, client=client)
        self.assertEqual(self.submit(sale, token, client=client).status_code, 403)
        self.assert_draft_unchanged(sale)
        csrf = client.cookies["csrftoken"].value
        response = self.submit(sale, token, client=client, csrfmiddlewaretoken=csrf)
        self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        self.assertTrue(sale.payment_is_simulated)

    def test_checkout_database_failures_return_generic_unavailable_responses(self):
        sale = self.draft_sale()
        token = self.checkout(sale)
        with self.assertLogs("commerce.payment_views", level="ERROR"), patch(
            "commerce.payment_views.simulate_payment", side_effect=DatabaseError("private database error"),
        ):
            response = self.submit(sale, token)
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private database error", status_code=503)
        self.assert_draft_unchanged(sale)

    def test_database_error_on_lookup_or_error_render_returns_503(self):
        sale = self.draft_sale()
        token = self.checkout(sale)
        for symbol, method, data in [
            ('payment_target', 'get', {}),
            ('payment_target', 'post', {'checkout_token': token, 'outcome': 'success'}),
            ('payment_amount', 'post', {'checkout_token': '', 'outcome': 'success'}),
        ]:
            with self.subTest(symbol=symbol, method=method):
                name = 'commerce:demo_payment' if method == 'get' else 'commerce:demo_payment_submit'
                with self.assertLogs('commerce.payment_views', level='ERROR'), patch(
                    'commerce.payment_views.' + symbol, side_effect=DatabaseError('private fault'),
                ):
                    response = getattr(self.client, method)(reverse(name, args=['sale', sale.pk]), data)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(b'private fault', response.content)
        self.assert_draft_unchanged(sale)

    def test_disabled_gateway_preserves_manual_electronic_completion_and_labels(self):
        sale = self.draft_sale()
        with override_settings(DEMO_PAYMENT_GATEWAY_ENABLED=False):
            response = self.client.get(reverse('commerce:sale_detail', args=[sale.pk]))
            self.assertContains(response, 'Complete sale')
            self.assertNotContains(response, 'Open demo checkout')
            for name in ['club:booking_create', 'club:public_availability']:
                page = self.client.get(reverse(name))
                self.assertNotContains(page, 'name="demo_gateway"')
                self.assertNotContains(page, 'Choose a demo outcome')
            response = self.client.post(reverse('commerce:sale_complete', args=[sale.pk]), {'demo_gateway': '1'})
            self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'completed')
        self.assertFalse(sale.payment_is_simulated)

    def test_paid_cancelled_and_zero_booking_checkout_render_no_payment_controls(self):
        booking = self.pending_booking()
        for changes in [{'payment_status': 'paid'}, {'status': 'cancelled'}, {'price': Decimal('0.00')}]:
            with self.subTest(changes=changes):
                Booking.objects.filter(pk=booking.pk).update(
                    **{'status': 'confirmed', 'payment_status': 'pending', 'price': Decimal('500.00'), **changes},
                )
                response = self.client.get(reverse('commerce:demo_payment', args=['booking', booking.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context['payable'])
                self.assertNotContains(response, 'name="outcome"')

    def test_booking_checkout_success_receipt_and_retry_use_existing_booking_routes(self):
        booking = self.pending_booking()
        token = self.checkout(booking, kind="booking")
        detail_url = reverse("club:booking_detail", args=[booking.pk])
        self.assertRedirects(self.submit(booking, token, kind="booking"), detail_url, fetch_redirect_response=False)
        booking.refresh_from_db()
        reference = booking.demo_payment_reference
        self.assertEqual((booking.payment_status, booking.price), ("paid", Decimal("500.00")))
        self.assertRedirects(self.submit(booking, token, kind="booking"), detail_url, fetch_redirect_response=False)
        booking.refresh_from_db()
        self.assertEqual(booking.demo_payment_reference, reference)
        receipt = self.client.get(reverse("club:booking_receipt", args=[booking.pk]))
        self.assertContains(receipt, reference)
        self.assertContains(receipt, "No money was charged or transferred")
        self.client.post(reverse('club:booking_cancel', args=[booking.pk]))
        receipt = self.client.get(reverse('club:booking_receipt', args=[booking.pk]))
        self.assertContains(receipt, 'Slot Released')
        self.assertContains(receipt, reference)
        self.assertContains(receipt, 'no real refund was processed')

    def test_booking_checkout_csrf_failure_and_cancel_leave_reservation_pending(self):
        booking = self.pending_booking()
        client = Client(enforce_csrf_checks=True)
        token = self.checkout(booking, kind="booking", client=client)
        self.assertEqual(self.submit(booking, token, kind="booking", client=client).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        failed = self.submit(booking, token, kind="booking", client=client,
                             outcome="failure", csrfmiddlewaretoken=csrf)
        self.assertContains(failed, "Simulated payment failed")
        cancelled = self.submit(booking, token, kind="booking", client=client,
                                outcome="cancel", csrfmiddlewaretoken=csrf)
        self.assertEqual(cancelled.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.payment_status), ("confirmed", "pending"))
        self.assertFalse(booking.payment_is_simulated)

    def test_existing_electronic_sale_complete_enters_simulator_but_cash_completes_normally(self):
        sale = self.draft_sale()
        response = self.client.post(reverse("commerce:sale_complete", args=[sale.pk]), {"demo_gateway": "1"})
        self.assertRedirects(response, reverse("commerce:demo_payment", args=["sale", sale.pk]), fetch_redirect_response=False)
        self.assert_draft_unchanged(sale)
        cash_sale = self.draft_sale(payment_method="cash")
        self.assertEqual(self.client.post(reverse("commerce:sale_complete", args=[cash_sale.pk]), {"demo_gateway": "1"}).status_code, 302)
        cash_sale.refresh_from_db()
        self.assertEqual(cash_sale.status, "completed")
        self.assertFalse(cash_sale.payment_is_simulated)

    def test_booking_form_electronic_checkout_cannot_claim_browser_paid_status(self):
        start = timezone.localtime().replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=1)
        response = self.client.post(reverse("club:booking_create"), {
            "court": str(self.court.pk), "walkin_name": "Checkout walk-in", "walkin_contact": "Demo",
            "start_datetime": start.strftime("%Y-%m-%dT%H:%M"), "booking_type": "standard",
            "payment_method": "upi", "payment_status": "paid", "demo_gateway": "1",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"], data)
        booking = Booking.objects.get(pk=data["booking_id"])
        self.assertEqual((booking.payment_status, booking.status), ("pending", "confirmed"))
        self.assertEqual(data["payment_url"], reverse("commerce:demo_payment", args=["booking", booking.pk]))
        self.assertFalse(booking.payment_is_simulated)


@skipUnless(connection.vendor == "postgresql", "Requires independent PostgreSQL row locks")
class DemoGatewayConcurrencyTests(GatewayFixtures, TransactionTestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Last checkout item", category="shop", price=Decimal("12.50"), stock_quantity=2,
        )
        self.court = Court.objects.create(name="Concurrent checkout court", hourly_rate=Decimal("500.00"))

    def parallel(self, calls):
        barrier = Barrier(len(calls))

        def worker(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '5s'")
                    cursor.execute("SET statement_timeout TO '10s'")
                barrier.wait(timeout=5)
                try:
                    return operation()
                except ValidationError as error:
                    return error.code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(worker, operation) for operation in calls]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_success_for_same_sale_deducts_once_and_returns_same_reference(self):
        sale = self.draft_sale()

        def success():
            target, result = self.pay(sale, amount=Decimal("25.00"))
            return result, target.demo_payment_reference

        results = self.parallel([success, success])
        self.assertCountEqual([result[0] for result in results], ["success", "already_successful"])
        self.assertEqual(results[0][1], results[1][1])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 0)

    def test_competing_simulated_sales_cannot_oversell(self):
        first, second = self.draft_sale(), self.draft_sale()
        results = self.parallel([
            lambda: self.pay(first, amount=Decimal("25.00"))[1],
            lambda: self.pay(second, amount=Decimal("25.00"))[1],
        ])
        self.assertCountEqual(results, ["success", "insufficient_stock"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 0)
        self.assertEqual(Sale.objects.filter(payment_is_simulated=True, status="completed").count(), 1)
        self.assertEqual(Sale.objects.filter(status="draft").count(), 1)

    def test_simulated_success_racing_sale_cancellation_finishes_cancelled_without_stock_loss(self):
        sale = self.draft_sale()
        results = self.parallel([
            lambda: self.pay(sale, amount=Decimal("25.00"))[1],
            lambda: cancel_sale(sale.pk).status,
        ])
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((sale.status, self.product.stock_quantity), (Sale.Status.CANCELLED, 2))
        self.assertIn(results[0], ["success", "invalid_sale_state"])
        self.assertEqual(results[1], Sale.Status.CANCELLED)

    def test_concurrent_booking_success_preserves_one_reference(self):
        booking = self.pending_booking()

        def success():
            target, result = self.pay(booking, kind="booking")
            return result, target.demo_payment_reference

        results = self.parallel([success, success])
        self.assertCountEqual([result[0] for result in results], ["success", "already_successful"])
        self.assertEqual(results[0][1], results[1][1])
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, "paid")
        self.assertTrue(booking.payment_is_simulated)

    def test_booking_payment_racing_cancellation_keeps_committed_payment_metadata(self):
        booking = self.pending_booking()

        def cancel_booking():
            # Exercise the actual route, including its lock and fresh-row read.
            response = Client().post(reverse('club:booking_cancel', args=[booking.pk]))
            self.assertEqual(response.status_code, 302)
            return Booking.objects.get(pk=booking.pk).status

        results = self.parallel([
            lambda: self.pay(booking, kind="booking")[1], cancel_booking,
        ])
        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(results[1], "cancelled")
        self.assertIn(results[0], ["success", "invalid_booking_state"])
        if results[0] == "success":
            self.assertEqual(booking.payment_status, "paid")
            self.assertTrue(booking.payment_is_simulated)
            self.assertRegex(booking.demo_payment_reference, r"^DEMO-[a-f0-9]{32}$")
        else:
            self.assertEqual(booking.payment_status, "pending")
            self.assertFalse(booking.payment_is_simulated)
