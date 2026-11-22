"""Real PostgreSQL business rules with mocked Razorpay TEST API responses.

The SDK signature verifier runs for real against fixture HMAC signatures. These
tests do not call Razorpay or establish that an external payment was executed.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import hashlib
import hmac
from threading import Barrier
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, connections
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
import razorpay
import requests

from club.models import Booking, Court, Member, MembershipPlan
from commerce.models import Product, Sale
from commerce.razorpay_gateway import (
    RazorpayConfigurationError, RazorpayUnavailable, TimeoutSession,
    amount_in_paise, create_test_order, test_client as configured_client,
    verify_test_payment,
)
from commerce.services import cancel_sale, create_sale, complete_sale
from commerce.demo_gateway import simulate_payment


TEST_KEY = 'rzp_test_fixture'
TEST_SECRET = 'fixture-test-secret'
TEST_SETTINGS = {
    'RAZORPAY_TEST_MODE_ENABLED': True,
    'RAZORPAY_KEY_ID': TEST_KEY,
    'RAZORPAY_KEY_SECRET': TEST_SECRET,
}


def signature(order_id, payment_id):
    return hmac.new(
        TEST_SECRET.encode(), f'{order_id}|{payment_id}'.encode(), hashlib.sha256,
    ).hexdigest()


def mock_provider():
    provider = MagicMock()
    # This is the official SDK verifier, not a mocked acceptance decision.
    provider.utility = razorpay.Client(auth=(TEST_KEY, TEST_SECRET)).utility
    provider.order.create.side_effect = lambda *, data: {
        'id': 'order_' + data['notes']['target_kind'] + data['notes']['target_id'],
        'amount': data['amount'], 'currency': 'INR',
    }
    return provider


def captured(target, payment_id='pay_fixture'):
    return {
        'id': payment_id, 'order_id': target.razorpay_order_id,
        'amount': int(target.razorpay_order_amount * 100), 'currency': 'INR',
        'method': 'card' if target.payment_method == 'card' else 'upi',
        'status': 'captured', 'captured': True, 'amount_refunded': 0,
    }


@override_settings(**TEST_SETTINGS)
class RazorpayConfigurationTests(SimpleTestCase):
    def test_missing_test_keys_or_disabled_mode_fail_without_provider_client(self):
        for changes in [
            {'RAZORPAY_KEY_ID': ''}, {'RAZORPAY_KEY_SECRET': ''},
            {'RAZORPAY_TEST_MODE_ENABLED': False},
        ]:
            with self.subTest(changes=changes), override_settings(**changes), patch(
                'commerce.razorpay_gateway.razorpay.Client',
            ) as constructor:
                with self.assertRaises(RazorpayConfigurationError):
                    configured_client()
                constructor.assert_not_called()

    def test_live_key_is_rejected_and_test_client_uses_official_api(self):
        with override_settings(RAZORPAY_KEY_ID='rzp_live_disallowed'):
            with self.assertRaises(RazorpayConfigurationError) as error:
                configured_client()
            self.assertIn('Live payments are disabled', str(error.exception))
        client = configured_client()
        self.assertEqual(client.auth, (TEST_KEY, TEST_SECRET))
        self.assertIsInstance(client.session, TimeoutSession)
        self.assertEqual(client.base_url, 'https://api.razorpay.com')

    def test_amount_conversion_uses_decimal_paise_and_rejects_invalid_amounts(self):
        self.assertEqual(amount_in_paise(Decimal('12.50')), 1250)
        self.assertEqual(amount_in_paise(Decimal('0.01')), 1)
        for amount in ['12.50', 12.5, Decimal('NaN'), Decimal('Infinity'),
                       Decimal('-1'), Decimal('0'), Decimal('1.001')]:
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                amount_in_paise(amount)

    def test_provider_http_requests_have_bounded_timeouts(self):
        with patch('requests.Session.request', return_value=object()) as request:
            TimeoutSession().request('GET', 'https://api.razorpay.com/v1/payments/pay_fixture')
        self.assertEqual(request.call_args.kwargs['timeout'], (3.05, 10))


class RazorpayFixtures:
    def set_provider(self):
        self.provider = mock_provider()
        self.provider_patch = patch('commerce.razorpay_gateway.test_client', return_value=self.provider)
        self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)
        # Views import the config-check function; no HTTP call is made by it.
        self.view_config_patch = patch('commerce.razorpay_views.test_client', return_value=self.provider)
        self.view_config_patch.start()
        self.addCleanup(self.view_config_patch.stop)

    def draft(self, *, method='UPI', quantity=2, member=None):
        return create_sale(
            quantities={self.product.pk: quantity}, payment_method=method,
            member_id=member.pk if member else None,
        )

    def booking(self, *, method='upi'):
        return Booking.objects.create(
            court=self.court, walkin_name='Razorpay test guest',
            start_datetime=timezone.localtime().replace(
                hour=10, minute=0, second=0, microsecond=0,
            ) + timedelta(days=1),
            status='confirmed', payment_method=method, payment_status='pending',
        )

    def order(self, target, *, kind='sale'):
        return create_test_order(kind, target.pk)

    def verify(self, target, *, kind='sale', payment_id='pay_fixture', **changes):
        values = {
            'kind': kind, 'pk': target.pk, 'order_id': target.razorpay_order_id,
            'payment_id': payment_id,
            'signature': signature(target.razorpay_order_id, payment_id),
        }
        values.update(changes)
        return verify_test_payment(**values)

    def assert_unpaid_sale(self, sale, *, stock=10):
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((sale.status, sale.total), ('draft', Decimal('0.00')))
        self.assertEqual(sale.razorpay_payment_id, '')
        self.assertFalse(sale.payment_is_simulated)
        self.assertEqual(sale.items.get().unit_price, Decimal('0.00'))
        self.assertEqual(self.product.stock_quantity, stock)


@override_settings(**TEST_SETTINGS)
@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL order/payment transactions')
class RazorpayServiceTests(RazorpayFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name='Razorpay test product', category='shop', price=Decimal('12.50'), stock_quantity=10,
        )
        cls.court = Court.objects.create(name='Razorpay test court', hourly_rate=Decimal('250.00'))

    def setUp(self):
        self.set_provider()

    def test_order_uses_server_price_in_paise_and_reuses_id_without_reserving_stock(self):
        sale = self.order(self.draft())
        data = self.provider.order.create.call_args.kwargs['data']
        self.assertEqual((data['amount'], data['currency'], data['partial_payment']), (2500, 'INR', False))
        self.assertEqual(data['notes'], {'target_kind': 'sale', 'target_id': str(sale.pk), 'mode': 'test'})
        self.assertLessEqual(len(data['receipt']), 40)
        self.assertEqual((sale.razorpay_order_amount, sale.razorpay_order_method), (Decimal('25.00'), 'UPI'))
        repeated = self.order(sale)
        self.assertEqual(repeated.razorpay_order_id, sale.razorpay_order_id)
        self.provider.order.create.assert_called_once()
        self.assert_unpaid_sale(sale)

    def test_saved_provider_order_blocks_manual_and_local_simulator_completion(self):
        sale = self.order(self.draft())
        with self.assertRaises(ValidationError) as error:
            complete_sale(sale.pk)
        self.assertEqual(error.exception.code, 'unverified_provider_payment')
        with self.assertRaises(ValidationError) as error:
            simulate_payment(kind='sale', pk=sale.pk, amount=Decimal('25.00'),
                             payment_method='UPI', outcome='success')
        self.assertEqual(error.exception.code, 'provider_order_exists')
        self.assert_unpaid_sale(sale)

    def test_order_and_verified_sale_preserve_shared_member_discount(self):
        plan = MembershipPlan.objects.create(
            tier='silver', name='Fixture Silver', shop_discount_percent=Decimal('10.00'),
        )
        member = Member.objects.create(name='Razorpay member fixture', plan=plan)
        sale = self.order(self.draft(method='card', member=member))
        self.assertEqual(sale.razorpay_order_amount, Decimal('22.50'))
        self.provider.payment.fetch.return_value = captured(sale)
        paid = self.verify(sale)
        self.assertEqual((paid.subtotal, paid.discount, paid.total),
                         (Decimal('25.00'), Decimal('2.50'), Decimal('22.50')))
        self.assertEqual(paid.items.get().discount, Decimal('2.50'))

    def test_bad_or_unavailable_provider_order_leaves_no_local_order(self):
        sale = self.draft()
        invalid = [None, {'id': 'bad'}, {'id': 'order_bad', 'amount': True, 'currency': 'INR'},
                   {'id': 'order_bad', 'amount': 2499, 'currency': 'INR'},
                   {'id': 'order_bad', 'amount': 2500, 'currency': 'USD'}]
        self.provider.order.create.side_effect = None
        for result in invalid:
            with self.subTest(result=result):
                self.provider.order.create.return_value = result
                with self.assertRaises(RazorpayUnavailable):
                    self.order(sale)
                sale.refresh_from_db()
                self.assertEqual(sale.razorpay_order_id, '')
                self.assertIsNone(sale.razorpay_order_amount)
        self.provider.order.create.side_effect = requests.Timeout('private API key detail')
        with self.assertRaises(RazorpayUnavailable) as error:
            self.order(sale)
        self.assertNotIn('private API key detail', str(error.exception))
        self.assert_unpaid_sale(sale)

    def test_captured_verified_payment_deducts_once_and_retains_same_payment_on_retry(self):
        sale = self.order(self.draft())
        self.provider.payment.fetch.return_value = captured(sale)
        paid = self.verify(sale)
        self.assertEqual((paid.status, paid.total, paid.razorpay_payment_id),
                         ('completed', Decimal('25.00'), 'pay_fixture'))
        self.assertTrue(paid.payment_is_simulated)
        self.assertEqual(paid.demo_payment_reference, '')
        retried = self.verify(sale)
        self.assertEqual(retried.razorpay_payment_id, 'pay_fixture')
        self.provider.payment.fetch.assert_called_once_with('pay_fixture')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

    def test_invalid_signature_and_cross_transaction_order_cannot_complete(self):
        sale = self.order(self.draft())
        with self.assertRaises(ValidationError) as error:
            self.verify(sale, signature='0' * 64)
        self.assertEqual(error.exception.code, 'invalid_signature')
        with self.assertRaises(ValidationError) as error:
            self.verify(sale, order_id='order_other', signature=signature('order_other', 'pay_fixture'))
        self.assertEqual(error.exception.code, 'invalid_order')
        self.provider.payment.fetch.assert_not_called()
        self.assert_unpaid_sale(sale)

    def test_unsigned_or_malformed_payment_ids_are_rejected_before_fetch(self):
        sale = self.order(self.draft())
        for changes in [{'payment_id': '../pay_fixture'}, {'signature': 'yes'},
                        {'order_id': None}, {'payment_id': 1}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.verify(sale, **changes)
        self.provider.payment.fetch.assert_not_called()
        self.assert_unpaid_sale(sale)

    def test_provider_capture_must_match_order_amount_currency_method_and_refund_state(self):
        sale = self.order(self.draft())
        baseline = captured(sale)
        changes_list = [
            {'id': 'pay_other'}, {'order_id': 'order_other'}, {'amount': 1}, {'amount': True},
            {'currency': 'USD'}, {'method': 'card'}, {'status': 'authorized'},
            {'status': 'failed'}, {'captured': False}, {'captured': 1}, {'amount_refunded': 1},
        ]
        for changes in changes_list:
            with self.subTest(changes=changes):
                self.provider.payment.fetch.return_value = {**baseline, **changes}
                with self.assertRaises(ValidationError) as error:
                    self.verify(sale)
                self.assertEqual(error.exception.code, 'unconfirmed_payment')
                self.assert_unpaid_sale(sale)

    def test_fetch_timeout_cannot_apply_payment_or_leak_provider_details(self):
        sale = self.order(self.draft())
        self.provider.payment.fetch.side_effect = requests.Timeout('private payment detail')
        with self.assertRaises(RazorpayUnavailable) as error:
            self.verify(sale)
        self.assertNotIn('private payment detail', str(error.exception))
        self.assert_unpaid_sale(sale)

    def test_price_or_method_drift_rejects_order_reuse_and_payment_without_writes(self):
        sale = self.order(self.draft())
        Product.objects.filter(pk=self.product.pk).update(price=Decimal('13.00'))
        for operation in [lambda: self.order(sale), lambda: self.verify(sale)]:
            with self.assertRaises(ValidationError) as error:
                operation()
            self.assertEqual(error.exception.code, 'stale_checkout')
        Product.objects.filter(pk=self.product.pk).update(price=Decimal('12.50'))
        Sale.objects.filter(pk=sale.pk).update(payment_method='card')
        with self.assertRaises(ValidationError) as error:
            self.verify(sale)
        self.assertEqual(error.exception.code, 'stale_checkout')
        self.provider.payment.fetch.assert_not_called()
        self.assert_unpaid_sale(sale)

    def test_stock_exhausted_after_order_prevents_local_completion(self):
        sale = self.order(self.draft())
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=1)
        with self.assertRaises(ValidationError) as error:
            self.verify(sale)
        self.assertEqual(error.exception.code, 'insufficient_stock')
        self.provider.payment.fetch.assert_not_called()
        self.assert_unpaid_sale(sale, stock=1)

    def test_payment_reference_write_failure_rolls_back_sale_snapshots_and_stock(self):
        sale = self.order(self.draft())
        self.provider.payment.fetch.return_value = captured(sale)
        original_save = Sale.save

        def fail_payment_save(instance, *args, **kwargs):
            if 'razorpay_payment_id' in kwargs.get('update_fields', []):
                raise RuntimeError('fixture payment reference failure')
            return original_save(instance, *args, **kwargs)

        with patch.object(Sale, 'save', autospec=True, side_effect=fail_payment_save):
            with self.assertRaises(RuntimeError):
                self.verify(sale)
        self.assert_unpaid_sale(sale)

    def test_cancelled_sale_cannot_apply_or_repeat_payment_and_stock_restores_once(self):
        sale = self.order(self.draft())
        self.provider.payment.fetch.return_value = captured(sale)
        paid = self.verify(sale)
        cancel_sale(paid.pk)
        cancel_sale(paid.pk)
        with self.assertRaises(ValidationError):
            self.verify(sale)
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((sale.status, self.product.stock_quantity), ('cancelled', 10))
        self.assertEqual(sale.razorpay_payment_id, 'pay_fixture')

    def test_booking_payment_and_retry_keep_confirmed_price_snapshot(self):
        booking = self.order(self.booking(), kind='booking')
        Court.objects.filter(pk=self.court.pk).update(hourly_rate=Decimal('999.00'))
        self.provider.payment.fetch.return_value = captured(booking)
        paid = self.verify(booking, kind='booking')
        self.assertEqual((paid.status, paid.payment_status, paid.price),
                         ('confirmed', 'paid', Decimal('250.00')))
        self.assertTrue(paid.payment_is_simulated)
        self.assertEqual(self.verify(booking, kind='booking').razorpay_payment_id, 'pay_fixture')
        self.provider.payment.fetch.assert_called_once()
        self.client.post(reverse('club:booking_cancel', args=[booking.pk]))
        with self.assertRaises(ValidationError):
            self.verify(booking, kind='booking')
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.razorpay_payment_id), ('cancelled', 'pay_fixture'))

    def test_free_cash_or_already_paid_booking_cannot_create_provider_order(self):
        booking = self.booking()
        for changes in [{'payment_status': 'paid'}, {'payment_method': 'cash'},
                        {'status': 'cancelled'}, {'price': Decimal('0.00')}]:
            with self.subTest(changes=changes):
                Booking.objects.filter(pk=booking.pk).update(
                    **{'status': 'confirmed', 'payment_status': 'pending', 'payment_method': 'upi',
                       'price': Decimal('250.00'), **changes},
                )
                with self.assertRaises(ValidationError):
                    self.order(booking, kind='booking')
        self.provider.order.create.assert_not_called()


@override_settings(**TEST_SETTINGS)
@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL checkout routes')
class RazorpayViewTests(RazorpayFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name='Razorpay route product', category='shop', price=Decimal('12.50'), stock_quantity=10,
        )
        cls.court = Court.objects.create(name='Razorpay route court', hourly_rate=Decimal('250.00'))

    def setUp(self):
        self.set_provider()

    def url(self, name, target, kind='sale'):
        return reverse('commerce:' + name, args=[kind, target.pk])

    def payment_data(self, target):
        return {
            'razorpay_order_id': target.razorpay_order_id, 'razorpay_payment_id': 'pay_fixture',
            'razorpay_signature': signature(target.razorpay_order_id, 'pay_fixture'),
        }

    def test_checkout_get_has_no_provider_order_or_business_writes(self):
        sale = self.draft()
        response = self.client.get(self.url('razorpay_payment', sale))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'commerce/razorpay_payment.html')
        self.assertContains(response, 'Razorpay Test Mode')
        self.assertContains(response, 'no real money charged')
        self.assertNotContains(response, TEST_SECRET)
        self.assertEqual(response.context['amount'], Decimal('25.00'))
        self.assertIsNone(response.context['checkout_config'])
        self.assertTrue(response.context['payable'])
        self.assertIn('no-store', response['Cache-Control'])
        self.provider.order.create.assert_not_called()
        self.assert_unpaid_sale(sale)

    def test_missing_keys_setup_returns_503_without_order_payment_controls(self):
        sale = self.draft()
        self.view_config_patch.stop()
        with override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET=''):
            response = self.client.get(self.url('razorpay_payment', sale))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, 'test keys are not configured', status_code=503)
        self.assertFalse(response.context['payable'])
        self.assertIsNone(response.context['checkout_config'])
        self.assertNotContains(response, 'id="razorpay-pay-button"', status_code=503)
        self.provider.order.create.assert_not_called()
        self.assert_unpaid_sale(sale)

    def test_order_post_ignores_caller_prices_and_returns_named_checkout_redirect(self):
        sale = self.draft()
        response = self.client.post(self.url('razorpay_order_create', sale), {
            'amount': '1', 'price': '0.01', 'payment_method': 'cash', 'next': 'https://example.com',
        })
        self.assertRedirects(response, self.url('razorpay_payment', sale), fetch_redirect_response=False)
        self.assertEqual(self.provider.order.create.call_args.kwargs['data']['amount'], 2500)
        self.assert_unpaid_sale(sale)

    def test_created_order_page_exposes_only_public_key_and_official_checkout(self):
        sale = self.order(self.draft(method='card'))
        response = self.client.get(self.url('razorpay_payment', sale))
        config = response.context['checkout_config']
        self.assertEqual((config['key'], config['order_id'], config['amount'], config['currency'], config['method']),
                         (TEST_KEY, sale.razorpay_order_id, 2500, 'INR', 'card'))
        self.assertEqual(config['verify_url'], self.url('razorpay_payment_verify', sale))
        self.assertContains(response, 'https://checkout.razorpay.com/v1/checkout.js')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotContains(response, TEST_SECRET)

    def test_verified_callback_ignores_extra_amount_and_retries_without_stock_loss(self):
        sale = self.order(self.draft())
        self.provider.payment.fetch.return_value = captured(sale)
        data = {**self.payment_data(sale), 'amount': '1', 'status': 'failed', 'next': 'https://example.com'}
        url = self.url('razorpay_payment_verify', sale)
        for _ in range(2):
            self.assertRedirects(self.client.post(url, data),
                                 reverse('commerce:sale_detail', args=[sale.pk]), fetch_redirect_response=False)
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((sale.status, sale.total, self.product.stock_quantity), ('completed', Decimal('25.00'), 8))
        self.provider.payment.fetch.assert_called_once()

    def test_csrf_required_for_order_and_verification_and_valid_csrf_succeeds(self):
        sale = self.draft()
        client = Client(enforce_csrf_checks=True)
        client.get(self.url('razorpay_payment', sale))
        csrf = client.cookies['csrftoken'].value
        for name in ['razorpay_order_create', 'razorpay_payment_verify']:
            self.assertEqual(client.post(self.url(name, sale), {}).status_code, 403)
        self.assertEqual(client.post(self.url('razorpay_order_create', sale), {'csrfmiddlewaretoken': csrf}).status_code, 302)
        sale.refresh_from_db()
        self.provider.payment.fetch.return_value = captured(sale)
        data = {**self.payment_data(sale), 'csrfmiddlewaretoken': csrf}
        self.assertEqual(client.post(self.url('razorpay_payment_verify', sale), data).status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'completed')

    def test_http_methods_missing_targets_and_disabled_checkout(self):
        sale = self.draft()
        display = self.url('razorpay_payment', sale)
        self.assertEqual(self.client.head(display).status_code, 200)
        self.assertEqual(self.client.post(display).status_code, 405)
        for name in ['razorpay_order_create', 'razorpay_payment_verify']:
            for method in ['get', 'head', 'put', 'delete']:
                with self.subTest(name=name, method=method):
                    self.assertEqual(getattr(self.client, method)(self.url(name, sale)).status_code, 405)
        for kind, pk in [('unknown', sale.pk), ('sale', sale.pk + 10000), ('booking', 10000)]:
            self.assertEqual(self.client.get(reverse('commerce:razorpay_payment', args=[kind, pk])).status_code, 404)
        with override_settings(RAZORPAY_TEST_MODE_ENABLED=False):
            self.assertEqual(self.client.get(display).status_code, 404)
            self.assertEqual(self.client.post(self.url('razorpay_order_create', sale), {}).status_code, 404)
        self.provider.order.create.assert_not_called()

    def test_bad_callback_form_and_signature_return_controlled_errors_without_mutation(self):
        sale = self.order(self.draft())
        url = self.url('razorpay_payment_verify', sale)
        self.assertEqual(self.client.post(url, {'razorpay_payment_id': 'bad'}).status_code, 400)
        response = self.client.post(url, {**self.payment_data(sale), 'razorpay_signature': '0' * 64})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'signature could not be verified', status_code=409)
        self.provider.payment.fetch.assert_not_called()
        self.assert_unpaid_sale(sale)

    def test_provider_or_database_outage_returns_generic_503_without_secret(self):
        sale = self.order(self.draft())
        self.provider.payment.fetch.side_effect = requests.Timeout('secret-provider-detail')
        response = self.client.post(self.url('razorpay_payment_verify', sale), self.payment_data(sale))
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'secret-provider-detail', status_code=503)
        with self.assertLogs('commerce.razorpay_views', level='ERROR'), patch(
            'commerce.razorpay_views._target', side_effect=DatabaseError('private-database-detail'),
        ):
            response = self.client.get(self.url('razorpay_payment', sale))
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'private-database-detail', status_code=503)
        self.assert_unpaid_sale(sale)

    def test_booking_form_routes_pending_electronic_reservation_to_actual_test_checkout(self):
        start = timezone.localtime().replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=1)
        response = self.client.post(reverse('club:booking_create'), {
            'court': self.court.pk, 'walkin_name': 'Actual test checkout guest',
            'start_datetime': start.strftime('%Y-%m-%dT%H:%M'), 'booking_type': 'standard',
            'payment_method': 'card', 'payment_status': 'paid', 'demo_gateway': '1',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'], data)
        booking = Booking.objects.get(pk=data['booking_id'])
        self.assertEqual((booking.status, booking.payment_status), ('confirmed', 'pending'))
        self.assertEqual(data['payment_url'], self.url('razorpay_payment', booking, 'booking'))
        self.provider.order.create.assert_not_called()


@override_settings(**TEST_SETTINGS)
@skipUnless(connection.vendor == 'postgresql', 'Requires independent PostgreSQL checkout locks')
class RazorpayConcurrencyTests(RazorpayFixtures, TransactionTestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name='Razorpay last stock', category='shop', price=Decimal('12.50'), stock_quantity=2,
        )
        self.set_provider()

    def parallel(self, operations):
        barrier = Barrier(len(operations))

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

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(worker, operation) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_order_creation_persists_one_provider_order(self):
        sale = self.draft()
        results = self.parallel([lambda: self.order(sale).razorpay_order_id] * 2)
        self.assertEqual(results[0], results[1])
        self.provider.order.create.assert_called_once()
        self.assert_unpaid_sale(sale, stock=2)

    def test_concurrent_verified_callbacks_deduct_stock_once(self):
        sale = self.order(self.draft())
        self.provider.payment.fetch.return_value = captured(sale)
        results = self.parallel([lambda: self.verify(sale).razorpay_payment_id] * 2)
        self.assertEqual(results, ['pay_fixture', 'pay_fixture'])
        self.provider.payment.fetch.assert_called_once()
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((sale.status, self.product.stock_quantity), ('completed', 0))

    def test_verified_callback_racing_cancellation_leaves_cancelled_sale_with_stock_restored(self):
        sale = self.order(self.draft())
        self.provider.payment.fetch.return_value = captured(sale)
        results = self.parallel([
            lambda: self.verify(sale).status,
            lambda: cancel_sale(sale.pk).status,
        ])
        sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((sale.status, self.product.stock_quantity), ('cancelled', 2))
        self.assertIn(results[0], ['completed', 'invalid_sale_state'])
        self.assertEqual(results[1], 'cancelled')
