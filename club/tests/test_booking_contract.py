"""Booking prices and form start times stay aligned with the shared contract."""
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from club.models import Booking, Court, Member, MembershipPlan
from club.plan_changes import change_membership_plan
from frontend.tests.helpers import login_test_staff


@skipUnless(connection.vendor == "postgresql", "Requires shared booking records")
class BookingContractRegressionTests(TestCase):
    def setUp(self):
        super().setUp()
        login_test_staff(self.client)

    @classmethod
    def setUpTestData(cls):
        cls.day = timezone.localdate() + timedelta(days=1)
        cls.court = Court.objects.create(name="Contract court", sport="tennis", hourly_rate=Decimal("500.00"))
        cls.plan = MembershipPlan.objects.create(tier="gold", name="Gold", court_hourly_rate=Decimal("0.00"))
        cls.member = Member.objects.create(name="Booking buyer", plan=cls.plan)

    def start(self, minute=0, second=0):
        return timezone.make_aware(datetime.combine(self.day, time(9, minute, second)))

    def test_model_and_booking_form_reject_non_half_hour_start(self):
        for minute, second in [(1, 0), (15, 0), (0, 1), (30, 1)]:
            with self.subTest(minute=minute, second=second):
                booking = Booking(court=self.court, walkin_name="Guest", start_datetime=self.start(minute, second))
                with self.assertRaises(ValidationError):
                    booking.full_clean()
        response = self.client.post(reverse("club:booking_create"), {
            "court": self.court.pk, "walkin_name": "Guest",
            "start_datetime": self.start(15).strftime("%Y-%m-%dT%H:%M"), "booking_type": "standard",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("start_datetime", response.context["form"].errors)
        self.assertEqual(Booking.objects.count(), 0)

    def test_confirmed_zero_price_remains_zero_after_plan_changes_and_save(self):
        booking = Booking.objects.create(court=self.court, booked_by_member=self.member,
            start_datetime=self.start(), status="confirmed")
        self.assertEqual(booking.price, Decimal("0.00"))
        MembershipPlan.objects.filter(pk=self.plan.pk).update(court_hourly_rate=Decimal("150.00"))
        booking.walkin_contact = "Updated contact"
        booking.save()
        booking.refresh_from_db()
        self.assertEqual(booking.price, Decimal("0.00"))

    def test_confirmation_validation_errors_render_without_creating_booking(self):
        for error in [
            ValidationError("The booking became unavailable."),
            ValidationError({"slot_range": "The booking became unavailable."}),
        ]:
            with self.subTest(error=error), patch("club.views.Booking.save", side_effect=error):
                response = self.client.post(reverse("club:booking_create"), {
                    "court": self.court.pk, "walkin_name": "Guest",
                    "start_datetime": self.start().strftime("%Y-%m-%dT%H:%M"),
                    "booking_type": "standard",
                })
            self.assertEqual(response.status_code, 200)
            self.assertIn("The booking became unavailable.", response.context["form"].non_field_errors())
            self.assertContains(response, "The booking became unavailable.")
            self.assertEqual(Booking.objects.count(), 0)
    def test_today_plan_assignment_counts_in_plan_management(self):
        silver = MembershipPlan.objects.create(tier="silver", name="Silver")
        change_membership_plan(member_id=self.member.pk, plan_id=silver.pk, effective_date=timezone.localdate())
        response = self.client.get(reverse("club:plan_list"))
        counts = {plan.pk: plan.member_count for plan in response.context["plans"]}
        self.assertEqual(counts[silver.pk], 1)
        self.assertEqual(counts[self.plan.pk], 0)

    def test_confirmed_price_stays_saved_after_scheduled_transition(self):
        booking = Booking.objects.create(court=self.court, booked_by_member=self.member,
            start_datetime=self.start(), status="confirmed")
        silver = MembershipPlan.objects.create(tier="silver", name="Silver", court_hourly_rate=Decimal("200.00"))
        change_membership_plan(member_id=self.member.pk, plan_id=silver.pk, effective_date=timezone.localdate())
        booking.refresh_from_db()
        booking.save()
        booking.refresh_from_db()
        self.assertEqual(booking.price, Decimal("0.00"))
