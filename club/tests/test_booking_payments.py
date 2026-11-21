"""
Tests for court booking payment options, snapshot rates, and settlement workflows.
"""
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from frontend.tests.helpers import login_test_staff
from django.utils import timezone
from django.urls import reverse
from club.models import Member, MembershipPlan, Court, Booking


class BookingPaymentTests(TestCase):
    def setUp(self):
        self.client = Client()
        login_test_staff(self.client)
        self.gold_plan = MembershipPlan.objects.create(
            tier='gold',
            name='Gold Plan',
            membership_fee=Decimal('5000.00'),
            court_hourly_rate=Decimal('0.00'),
            active=True
        )
        self.silver_plan = MembershipPlan.objects.create(
            tier='silver',
            name='Silver Plan',
            membership_fee=Decimal('2500.00'),
            court_hourly_rate=Decimal('200.00'),
            active=True
        )
        today = timezone.localdate()
        self.gold_member = Member.objects.create(
            name='Gold Champion',
            email='gold@example.com',
            phone='9999911111',
            plan=self.gold_plan,
            membership_start=today - timedelta(days=10),
            membership_end=today + timedelta(days=350),
            is_club_member=True,
            is_suspended=False
        )
        self.silver_member = Member.objects.create(
            name='Silver Striker',
            email='silver@example.com',
            phone='9999922222',
            plan=self.silver_plan,
            membership_start=today - timedelta(days=10),
            membership_end=today + timedelta(days=350),
            is_club_member=True,
            is_suspended=False
        )
        self.court = Court.objects.create(
            name='Center Court (Tennis)',
            sport='tennis',
            hourly_rate=Decimal('500.00'),
            active=True
        )

    def test_walkin_booking_with_upi_payment(self):
        """Walk-in booking standard rate settled via UPI."""
        now = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
        url = reverse('club:booking_create')
        data = {
            'court': self.court.id,
            'walkin_name': 'Rohit Sharma',
            'walkin_contact': '+91 9888877777',
            'start_datetime': now.strftime('%Y-%m-%dT%H:%M'),
            'booking_type': 'standard',
            'payment_method': 'upi',
            'payment_status': 'paid',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        booking = Booking.objects.get(walkin_name='Rohit Sharma')
        self.assertEqual(booking.price, Decimal('500.00'))
        self.assertEqual(booking.payment_method, 'upi')
        self.assertEqual(booking.payment_status, 'paid')
        self.assertEqual(booking.status, 'confirmed')

    def test_walkin_booking_ajax_returns_payment_details(self):
        """In-web AJAX reservation pop-up returns payment metadata."""
        now = timezone.localtime().replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=1)
        url = reverse('club:booking_create')
        data = {
            'court': self.court.id,
            'walkin_name': 'Virat Kohli',
            'walkin_contact': '+91 9777766666',
            'start_datetime': now.strftime('%Y-%m-%dT%H:%M'),
            'booking_type': 'standard',
            'payment_method': 'card',
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        res_json = response.json()
        self.assertTrue(res_json['success'])
        self.assertEqual(res_json['payment_method'], 'card')
        self.assertIn('Card', res_json['payment_method_display'])
        self.assertEqual(res_json['price'], 500.0)

    def test_gold_member_auto_waives_court_fee_with_member_tab(self):
        """Gold plan members (free court) automatically receive fee waiver and member tab."""
        now = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=1)
        url = reverse('club:booking_create')
        data = {
            'court': self.court.id,
            'booked_by_member': self.gold_member.id,
            'start_datetime': now.strftime('%Y-%m-%dT%H:%M'),
            'booking_type': 'standard',
            'payment_method': 'member_tab',
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        res_json = response.json()
        self.assertTrue(res_json['success'])
        self.assertEqual(res_json['price'], 0.0)
        self.assertEqual(res_json['payment_status'], 'waived')
        self.assertEqual(res_json['payment_method'], 'member_tab')

    def test_silver_member_discounted_rate_with_cash(self):
        """Silver plan members pay tier entitlement rate (₹200) settled via cash."""
        now = timezone.localtime().replace(hour=13, minute=0, second=0, microsecond=0) + timedelta(days=1)
        url = reverse('club:booking_create')
        data = {
            'court': self.court.id,
            'booked_by_member': self.silver_member.id,
            'start_datetime': now.strftime('%Y-%m-%dT%H:%M'),
            'booking_type': 'standard',
            'payment_method': 'cash',
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        res_json = response.json()
        self.assertTrue(res_json['success'])
        self.assertEqual(res_json['price'], 200.0)
        self.assertEqual(res_json['payment_method'], 'cash')
        self.assertEqual(res_json['payment_status'], 'paid')

    def test_booking_receipt_view(self):
        """Official booking voucher returns HTTP 200 and renders voucher details."""
        now = timezone.localtime().replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1)
        booking = Booking.objects.create(
            court=self.court,
            booked_by_member=self.silver_member,
            start_datetime=now,
            end_datetime=now + timedelta(minutes=60),
            status='confirmed',
            price=Decimal('200.00'),
            payment_method='upi',
            payment_status='paid'
        )
        url = reverse('club:booking_receipt', kwargs={'pk': booking.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Booking Voucher')
        self.assertContains(response, 'Center Court (Tennis)')
        self.assertContains(response, 'Silver Striker')
        self.assertContains(response, 'GATE-PASS-AUTH')

    def test_booking_detail_ajax_inspection(self):
        """AJAX inspection query returns JSON payload with slot and player metadata."""
        now = timezone.localtime().replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=1)
        booking = Booking.objects.create(
            court=self.court,
            booked_by_member=self.gold_member,
            start_datetime=now,
            end_datetime=now + timedelta(minutes=60),
            status='confirmed',
            price=Decimal('0.00'),
            payment_method='member_tab',
            payment_status='waived'
        )
        url = reverse('club:booking_detail', kwargs={'pk': booking.id})
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['player_name'], 'Gold Champion')
        self.assertEqual(data['tier_name'], 'Gold Plan')
        self.assertEqual(data['price'], 0.0)
        self.assertIn('receipt_url', data)

    def test_booking_cancel_ajax_releases_slot(self):
        """AJAX cancellation cancels booking and returns slot details for instant UI release."""
        now = timezone.localtime().replace(hour=16, minute=0, second=0, microsecond=0) + timedelta(days=1)
        booking = Booking.objects.create(
            court=self.court,
            walkin_name='Hardik Pandya',
            start_datetime=now,
            end_datetime=now + timedelta(minutes=60),
            status='confirmed',
            price=Decimal('500.00'),
            payment_method='cash',
            payment_status='paid'
        )
        url = reverse('club:booking_cancel', kwargs={'pk': booking.id})
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['slot_hour'], '16:00')

        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
