"""Customer account ownership and shared business rules on real PostgreSQL.

Provider network calls are not made by these tests. Checkout routing and local
simulation exercise actual Django sessions, CSRF and persisted commerce data.
"""

from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from club.models import Booking, Court, Member, MembershipPlan
from commerce.models import Product, Sale
from commerce.services import complete_sale, quote_sale
from frontend.customer_forms import CustomerBookingForm, CustomerRegistrationForm, CustomerSaleForm
from frontend.customer_services import create_customer_booking, create_customer_sale
from frontend.models import CustomerAccount


TEST_PASSWORD = 'Portal-fixture-27!z'


class CustomerFixtures:
    @classmethod
    def make_records(cls):
        users = get_user_model()
        cls.alice = users.objects.create_user(username='portal-alice', first_name='Alice Portal',
                                             email='alice@example.test', password=TEST_PASSWORD)
        cls.bob = users.objects.create_user(username='portal-bob', first_name='Bob Private',
                                           email='bob@example.test', password=TEST_PASSWORD)
        cls.staff = users.objects.create_user(username='portal-staff', password=TEST_PASSWORD, is_staff=True)
        cls.alice_account = CustomerAccount.objects.create(user=cls.alice)
        cls.bob_account = CustomerAccount.objects.create(user=cls.bob)
        cls.product = Product.objects.create(name='Portal tennis balls', category='shop',
                                             price=Decimal('12.50'), stock_quantity=10)
        cls.inactive_product = Product.objects.create(name='Inactive private product', category='bar',
                                                      price=Decimal('2.00'), stock_quantity=10, is_active=False)
        cls.court = Court.objects.create(name='Portal Court', hourly_rate=Decimal('250.00'), active=True)
        cls.inactive_court = Court.objects.create(name='Closed Court', hourly_rate=Decimal('200.00'), active=False)
        cls.plan = MembershipPlan.objects.create(name='Portal Silver', tier='silver',
                                                 court_hourly_rate=Decimal('200.00'),
                                                 shop_discount_percent=Decimal('10.00'),
                                                 bar_discount_percent=Decimal('5.00'), active=True)
        cls.member = Member.objects.create(name='Existing private member', email='member@example.test', plan=cls.plan)
        cls.day = timezone.localdate() + timedelta(days=3)

    def sign_in(self, user=None, client=None):
        client = client or self.client
        client.force_login(user or self.alice)
        return client

    def draft(self, user=None):
        return create_customer_sale(user or self.alice, product=self.product, quantity=2, payment_method='card')

    def booking(self, user=None, *, hour=10):
        start = timezone.localtime().replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=3)
        return create_customer_booking(user or self.alice, court=self.court,
                                       start_datetime=start, payment_method='card')

    def sale_data(self, **changes):
        data = {'product': str(self.product.pk), 'quantity': '2', 'payment_method': 'card'}
        data.update(changes)
        return data

    def booking_data(self, **changes):
        data = {'court': str(self.court.pk), 'date': self.day.isoformat(),
                'start_time': '10:00', 'payment_method': 'card'}
        data.update(changes)
        return data

    def assert_stock(self, expected=10):
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, expected)


@override_settings(RAZORPAY_TEST_MODE_ENABLED=False, DEMO_PAYMENT_GATEWAY_ENABLED=True)
@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL customer records')
class CustomerAccountTests(CustomerFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_records()

    def registration_data(self, **changes):
        data = {'username': 'new-portal-user', 'first_name': 'New Customer', 'email': self.member.email,
                'password1': TEST_PASSWORD, 'password2': TEST_PASSWORD}
        data.update(changes)
        return data

    def test_signup_hashes_password_and_cannot_claim_existing_member_or_staff_role(self):
        before = Member.objects.count()
        response = self.client.post(reverse('customer:register'), self.registration_data(
            member=str(self.member.pk), customer=str(self.bob.pk), is_staff='1', is_superuser='1',
        ))
        self.assertRedirects(response, reverse('customer:dashboard'), fetch_redirect_response=False)
        user = get_user_model().objects.get(username='new-portal-user')
        self.assertTrue(user.check_password(TEST_PASSWORD))
        self.assertNotEqual(user.password, TEST_PASSWORD)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertIsNone(user.customer_account.member_id)
        self.assertEqual(Member.objects.count(), before)
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_signup_rejects_duplicate_username_bad_email_and_password_mismatch(self):
        before = get_user_model().objects.count()
        for changes, field in [({'username': self.alice.username}, 'username'),
                               ({'email': 'invalid-address'}, 'email'),
                               ({'password2': 'different-value'}, 'password2')]:
            with self.subTest(changes=changes):
                response = self.client.post(reverse('customer:register'), self.registration_data(**changes))
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.context['form'].errors)
        self.assertEqual(get_user_model().objects.count(), before)

    def test_login_rejects_invalid_password_and_external_next_redirect(self):
        response = self.client.post(reverse('customer:login'), {
            'username': self.alice.username, 'password': 'wrong-password',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        response = self.client.post(reverse('customer:login'), {
            'username': self.alice.username, 'password': TEST_PASSWORD, 'next': 'https://example.test/',
        })
        self.assertRedirects(response, reverse('customer:dashboard'), fetch_redirect_response=False)

    def test_login_allows_safe_customer_next_and_inactive_user_cannot_login(self):
        destination = reverse('customer:booking_create')
        response = self.client.post(reverse('customer:login'), {
            'username': self.alice.username, 'password': TEST_PASSWORD, 'next': destination,
        })
        self.assertRedirects(response, destination, fetch_redirect_response=False)
        self.client.logout()
        self.alice.is_active = False
        self.alice.save(update_fields=['is_active'])
        response = self.client.post(reverse('customer:login'), {
            'username': self.alice.username, 'password': TEST_PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_is_post_only_and_clears_customer_session(self):
        self.sign_in()
        self.assertEqual(self.client.get(reverse('customer:logout')).status_code, 405)
        response = self.client.post(reverse('customer:logout'))
        self.assertRedirects(response, reverse('customer:home'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_account_page_lists_only_current_users_transactions_and_member(self):
        own_sale = self.draft()
        other_sale = self.draft(self.bob)
        own_booking = self.booking()
        other_booking = self.booking(self.bob, hour=12)
        self.sign_in()
        response = self.client.get(reverse('customer:dashboard'))
        self.assertEqual(list(response.context['sales']), [own_sale])
        self.assertEqual(list(response.context['bookings']), [own_booking])
        self.assertNotIn(other_sale, response.context['sales'])
        self.assertNotIn(other_booking, response.context['bookings'])
        self.assertNotContains(response, self.bob.first_name)
        self.assertIsNone(response.context['member'])

    def test_staff_verified_member_link_is_used_without_duplicate_members(self):
        count = Member.objects.count()
        self.alice_account.member = self.member
        self.alice_account.save(update_fields=['member'])
        sale = self.draft()
        self.assertEqual(sale.member_id, self.member.pk)
        self.assertEqual(quote_sale(sale.pk), Decimal('22.50'))
        booking = self.booking()
        self.assertEqual(booking.booked_by_member_id, self.member.pk)
        self.assertEqual(booking.price, Decimal('200.00'))
        self.assertEqual(booking.participants.get().member_id, self.member.pk)
        self.assertEqual(Member.objects.count(), count)

    def test_public_browsing_shows_active_products_courts_and_plans_without_personal_data(self):
        private_booking = self.booking(self.bob)
        for name in ['home', 'shop', 'plans', 'courts']:
            with self.subTest(name=name):
                response = self.client.get(reverse('customer:' + name), {'date': self.day.isoformat()})
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, self.bob.first_name)
                self.assertNotContains(response, self.member.name)
                self.assertNotContains(response, reverse('club:member_list'))
                self.assertNotContains(response, reverse('club:booking_export_csv'))
        response = self.client.get(reverse('customer:shop'))
        self.assertEqual(list(response.context['products']), [self.product])
        response = self.client.get(reverse('customer:courts'), {'date': self.day.isoformat()})
        self.assertEqual([row['court'] for row in response.context['court_grid']], [self.court])
        slot_payloads = [payload for row in response.context['court_grid'] for _, payload in row['slots']]
        self.assertTrue(any(payload['status'] == 'booked' for payload in slot_payloads))
        self.assertTrue(all(set(payload) == {'status'} for payload in slot_payloads))
        self.assertNotContains(response, reverse('customer:booking_detail', args=[private_booking.pk]))

    def test_product_and_court_links_preselect_only_real_active_records(self):
        response = self.client.get(reverse('customer:shop'), {'product': self.product.pk})
        self.assertEqual(response.context['form'].initial['product'], self.product.pk)
        self.assertEqual(self.client.get(reverse('customer:shop'), {'product': self.inactive_product.pk}).status_code, 404)
        response = self.client.get(reverse('customer:courts'), {'court': self.court.pk, 'date': self.day.isoformat()})
        self.assertEqual([row['court'].pk for row in response.context['court_grid']], [self.court.pk])
        for value in ['invalid', str(self.inactive_court.pk), '999999999999999999999999']:
            self.assertEqual(self.client.get(reverse('customer:courts'), {'court': value}).status_code, 404)

    def test_past_sessions_are_not_offered_as_available(self):
        response = self.client.get(reverse('customer:courts'), {'date': (timezone.localdate() - timedelta(days=1)).isoformat()})
        self.assertTrue(all(slot['status'] == 'past' for row in response.context['court_grid'] for _, slot in row['slots']))
        self.assertNotContains(response, 'Book session')


@override_settings(RAZORPAY_TEST_MODE_ENABLED=False, DEMO_PAYMENT_GATEWAY_ENABLED=True)
@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL customer workflows')
class CustomerWorkflowTests(CustomerFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_records()

    def test_customer_forms_expose_only_owned_transaction_inputs(self):
        self.assertEqual(set(CustomerSaleForm().fields), {'product', 'quantity', 'payment_method'})
        self.assertEqual(set(CustomerBookingForm().fields), {'court', 'date', 'start_time', 'payment_method'})
        self.assertEqual(set(CustomerRegistrationForm().fields), {'username', 'first_name', 'email', 'password1', 'password2'})

    def test_protected_customer_pages_and_posts_require_login(self):
        sale = self.draft()
        booking = self.booking()
        requests = [('dashboard', [], 'get', {}), ('booking_create', [], 'get', {}),
                    ('sale_detail', [sale.pk], 'get', {}), ('booking_detail', [booking.pk], 'get', {}),
                    ('checkout', ['sale', sale.pk], 'get', {}), ('sale_create', [], 'post', self.sale_data()),
                    ('booking_create', [], 'post', self.booking_data()),
                    ('sale_cancel', [sale.pk], 'post', {}), ('booking_cancel', [booking.pk], 'post', {})]
        for name, args, method, data in requests:
            with self.subTest(name=name, method=method):
                response = getattr(self.client, method)(reverse('customer:' + name, args=args), data)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse('customer:login') + '?'))
        self.assert_stock()

    def test_create_sale_assigns_session_owner_and_ignores_spoofed_fields(self):
        self.sign_in()
        response = self.client.post(reverse('customer:sale_create'), self.sale_data(
            member=str(self.member.pk), customer=str(self.bob.pk), price='0.01', total='1.00', stock='999', status='completed',
        ))
        sale = Sale.objects.get()
        self.assertRedirects(response, reverse('customer:sale_detail', args=[sale.pk]), fetch_redirect_response=False)
        self.assertEqual(sale.customer_id, self.alice.pk)
        self.assertIsNone(sale.member_id)
        self.assertEqual(sale.status, 'draft')
        self.assertEqual(sale.total, Decimal('0.00'))
        self.assert_stock()

    def test_sale_form_rejects_inactive_product_bad_quantity_and_cash(self):
        self.sign_in()
        for changes, field in [({'product': self.inactive_product.pk}, 'product'),
                               ({'quantity': '0'}, 'quantity'), ({'quantity': '1.5'}, 'quantity'),
                               ({'payment_method': 'cash'}, 'payment_method')]:
            with self.subTest(changes=changes):
                response = self.client.post(reverse('customer:sale_create'), self.sale_data(**changes))
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.context['form'].errors)
        self.assertFalse(Sale.objects.exists())
        self.assert_stock()

    def test_create_booking_owns_session_identity_and_keeps_payment_pending(self):
        self.sign_in()
        response = self.client.post(reverse('customer:booking_create'), self.booking_data(
            booked_by_member=str(self.member.pk), customer=str(self.bob.pk),
            payment_status='paid', price='0.01', status='cancelled',
        ))
        booking = Booking.objects.get()
        self.assertRedirects(response, reverse('customer:booking_detail', args=[booking.pk]), fetch_redirect_response=False)
        self.assertEqual(booking.customer_id, self.alice.pk)
        self.assertIsNone(booking.booked_by_member_id)
        self.assertEqual(booking.walkin_name, self.alice.first_name)
        self.assertEqual((booking.status, booking.payment_status, booking.price), ('confirmed', 'pending', Decimal('250.00')))
        self.assertEqual(booking.end_datetime - booking.start_datetime, timedelta(minutes=60))

    def test_booking_rejects_past_far_future_misaligned_or_inactive_court(self):
        self.sign_in()
        cases = [({'date': (timezone.localdate() - timedelta(days=1)).isoformat()}, 'date'),
                 ({'date': (timezone.localdate() + timedelta(days=91)).isoformat()}, 'date'),
                 ({'start_time': '10:15'}, 'start_time'), ({'court': self.inactive_court.pk}, 'court')]
        for changes, field in cases:
            with self.subTest(changes=changes):
                response = self.client.post(reverse('customer:booking_create'), self.booking_data(**changes))
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.context['form'].errors)
        self.assertFalse(Booking.objects.exists())

    def test_overlapping_booking_is_rejected_by_shared_rule(self):
        self.booking(self.bob)
        self.sign_in()
        response = self.client.post(reverse('customer:booking_create'), self.booking_data(start_time='10:30'))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(Booking.objects.count(), 1)

    def test_third_member_booking_on_same_date_is_rejected(self):
        self.alice_account.member = self.member
        self.alice_account.save(update_fields=['member'])
        self.booking(hour=8)
        self.booking(hour=10)
        self.sign_in()
        response = self.client.post(reverse('customer:booking_create'), self.booking_data(start_time='12:00'))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(Booking.objects.count(), 2)

    def test_unpaid_sale_cancellation_is_idempotent_and_does_not_restock(self):
        sale = self.draft()
        self.sign_in()
        for _ in range(2):
            response = self.client.post(reverse('customer:sale_cancel', args=[sale.pk]))
            self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'cancelled')
        self.assert_stock()

    def test_completed_sale_cannot_be_cancelled_by_customer_or_legacy_bypass(self):
        sale = complete_sale(self.draft().pk)
        self.sign_in()
        response = self.client.post(reverse('customer:sale_cancel', args=[sale.pk]), follow=True)
        self.assertContains(response, 'Contact the club')
        self.assertEqual(self.client.post(reverse('commerce:sale_cancel', args=[sale.pk])).status_code, 404)
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'completed')
        self.assert_stock(8)

    def test_unpaid_booking_cancel_releases_slot_once_and_paid_booking_requires_staff(self):
        booking = self.booking()
        self.sign_in()
        for _ in range(2):
            self.assertEqual(self.client.post(reverse('customer:booking_cancel', args=[booking.pk])).status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        paid = self.booking(hour=12)
        Booking.objects.filter(pk=paid.pk).update(payment_status='paid')
        response = self.client.post(reverse('customer:booking_cancel', args=[paid.pk]), follow=True)
        self.assertContains(response, 'Contact the club')
        self.assertEqual(self.client.post(reverse('club:booking_cancel', args=[paid.pk])).status_code, 404)
        paid.refresh_from_db()
        self.assertEqual(paid.status, 'confirmed')

    def test_sale_detail_uses_saved_snapshots_after_catalogue_price_change(self):
        sale = complete_sale(self.draft().pk)
        Product.objects.filter(pk=self.product.pk).update(price=Decimal('99.00'))
        self.sign_in()
        response = self.client.get(reverse('customer:sale_detail', args=[sale.pk]))
        self.assertEqual(response.context['sale'].total, Decimal('25.00'))
        self.assertEqual(list(response.context['sale_items'])[0].unit_price, Decimal('12.50'))
        self.assert_stock(8)

    def test_customer_mutation_routes_are_post_only(self):
        sale = self.draft()
        booking = self.booking()
        self.sign_in()
        for name, args in [('sale_create', []), ('sale_cancel', [sale.pk]), ('booking_cancel', [booking.pk]), ('logout', [])]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse('customer:' + name, args=args)).status_code, 405)
        self.assert_stock()

    def test_sale_and_booking_service_errors_return_generic_503(self):
        self.sign_in()
        for symbol, name, data in [('create_customer_sale', 'sale_create', self.sale_data()),
                                   ('create_customer_booking', 'booking_create', self.booking_data())]:
            with self.subTest(symbol=symbol), self.assertLogs('frontend.customer_views', level='ERROR'), patch(
                'frontend.customer_views.' + symbol, side_effect=DatabaseError('private injected fault'),
            ):
                response = self.client.post(reverse('customer:' + name), data)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(b'private injected fault', response.content)
        self.assert_stock()


@override_settings(RAZORPAY_TEST_MODE_ENABLED=False, DEMO_PAYMENT_GATEWAY_ENABLED=True)
@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL record authorization')
class CustomerAuthorizationTests(CustomerFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_records()

    def test_other_customer_cannot_view_cancel_or_pay_owner_records(self):
        sale = self.draft()
        booking = self.booking()
        self.sign_in(self.bob)
        for name, args, method in [('sale_detail', [sale.pk], 'get'), ('booking_detail', [booking.pk], 'get'),
                                   ('sale_cancel', [sale.pk], 'post'), ('booking_cancel', [booking.pk], 'post'),
                                   ('checkout', ['sale', sale.pk], 'get'), ('checkout', ['booking', booking.pk], 'get')]:
            with self.subTest(name=name):
                self.assertEqual(getattr(self.client, method)(reverse('customer:' + name, args=args)).status_code, 404)
        self.assert_stock()

    def test_anonymous_and_other_account_cannot_use_legacy_detail_receipt_or_payment_routes(self):
        sale = self.draft()
        booking = self.booking()
        routes = [('commerce:sale_detail', [sale.pk], 'get'), ('commerce:sale_receipt', [sale.pk], 'get'),
                  ('commerce:sale_cancel', [sale.pk], 'post'), ('commerce:sale_complete', [sale.pk], 'post'),
                  ('club:booking_detail', [booking.pk], 'get'), ('club:booking_receipt', [booking.pk], 'get'),
                  ('club:booking_cancel', [booking.pk], 'post')]
        for name in ['commerce:demo_payment', 'commerce:demo_payment_submit', 'commerce:razorpay_payment',
                     'commerce:razorpay_order_create', 'commerce:razorpay_payment_verify']:
            routes.append((name, ['sale', sale.pk], 'post' if name.endswith(('submit', 'create', 'verify')) else 'get'))
            routes.append((name, ['booking', booking.pk], 'post' if name.endswith(('submit', 'create', 'verify')) else 'get'))
        for user in [None, self.bob]:
            client = Client()
            if user:
                client.force_login(user)
            for name, args, method in routes:
                with self.subTest(user=user, name=name, args=args):
                    self.assertEqual(getattr(client, method)(reverse(name, args=args)).status_code, 404)
        self.assert_stock()

    def test_owning_customer_cannot_bypass_portal_rules_via_legacy_mutations(self):
        sale = self.draft()
        booking = self.booking()
        self.sign_in()
        for name, args in [('commerce:sale_complete', [sale.pk]), ('commerce:sale_cancel', [sale.pk]),
                           ('club:booking_cancel', [booking.pk]), ('club:booking_detail', [booking.pk])]:
            with self.subTest(name=name):
                self.assertEqual(self.client.post(reverse(name, args=args)).status_code, 404)
        sale.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual((sale.status, booking.status), ('draft', 'confirmed'))
        self.assert_stock()

    def test_staff_can_operate_owned_records_and_existing_anonymous_counter_stays_available(self):
        sale = self.draft()
        self.sign_in(self.staff)
        self.assertEqual(self.client.get(reverse('commerce:sale_detail', args=[sale.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('commerce:sale_cancel', args=[sale.pk])).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('commerce:guest_counter')).status_code, 200)

    def test_checkout_redirects_to_provider_when_enabled_and_handles_disabled_payments(self):
        sale = self.draft()
        self.sign_in()
        url = reverse('customer:checkout', args=['sale', sale.pk])
        with override_settings(RAZORPAY_TEST_MODE_ENABLED=True):
            self.assertRedirects(self.client.get(url), reverse('commerce:razorpay_payment', args=['sale', sale.pk]),
                                 fetch_redirect_response=False)
        self.assertRedirects(self.client.get(url), reverse('commerce:demo_payment', args=['sale', sale.pk]),
                             fetch_redirect_response=False)
        with override_settings(RAZORPAY_TEST_MODE_ENABLED=False, DEMO_PAYMENT_GATEWAY_ENABLED=False):
            self.assertEqual(self.client.get(url).status_code, 503)
        self.assertEqual(self.client.get(reverse('customer:checkout', args=['unknown', sale.pk])).status_code, 404)

    def test_local_checkout_renders_customer_navigation_and_returns_to_own_sale(self):
        sale = self.draft()
        self.sign_in()
        response = self.client.get(reverse('commerce:demo_payment', args=['sale', sale.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'customer/demo_payment.html')
        self.assertEqual(response.context['return_url'], reverse('customer:sale_detail', args=[sale.pk]))
        token = response.context['checkout_token']
        response = self.client.post(reverse('commerce:demo_payment_submit', args=['sale', sale.pk]), {
            'checkout_token': token, 'outcome': 'success',
        })
        self.assertRedirects(response, reverse('customer:sale_detail', args=[sale.pk]), fetch_redirect_response=False)
        self.assert_stock(8)

    def test_razorpay_checkout_uses_customer_template_and_verified_success_returns_to_account(self):
        sale = self.draft()
        self.sign_in()
        with override_settings(RAZORPAY_TEST_MODE_ENABLED=True, RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET=''):
            response = self.client.get(reverse('commerce:razorpay_payment', args=['sale', sale.pk]))
            self.assertEqual(response.status_code, 503)
            self.assertTemplateUsed(response, 'customer/razorpay_payment.html')
            self.assertEqual(response.context['return_url'], reverse('customer:sale_detail', args=[sale.pk]))
            with patch('commerce.razorpay_views.verify_test_payment', return_value=sale):
                response = self.client.post(reverse('commerce:razorpay_payment_verify', args=['sale', sale.pk]), {
                    'razorpay_order_id': 'order_fixture', 'razorpay_payment_id': 'pay_fixture',
                    'razorpay_signature': 'a' * 64,
                })
            self.assertRedirects(response, reverse('customer:sale_detail', args=[sale.pk]), fetch_redirect_response=False)
        self.assert_stock()

    def test_customer_forms_and_all_state_changes_enforce_csrf(self):
        sale = self.draft()
        booking = self.booking()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        for name, args, data in [('sale_create', [], self.sale_data()), ('booking_create', [], self.booking_data()),
                                 ('sale_cancel', [sale.pk], {}), ('booking_cancel', [booking.pk], {}), ('logout', [], {})]:
            with self.subTest(name=name):
                self.assertEqual(client.post(reverse('customer:' + name, args=args), data).status_code, 403)
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('customer:register'), {}).status_code, 403)
        client.get(reverse('customer:shop'))
        csrf = client.cookies['csrftoken'].value
        response = client.post(reverse('customer:sale_create'), self.sale_data(), HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Sale.objects.filter(customer=self.alice).count(), 2)
        self.assert_stock()
