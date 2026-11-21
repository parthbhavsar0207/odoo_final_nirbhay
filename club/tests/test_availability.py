"""Public half-hour availability matches confirmed PostgreSQL intervals."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import skipUnless

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from club.availability import availability_grid
from club.models import Booking, Court, Member, MembershipPlan


@skipUnless(connection.vendor == "postgresql", "Requires actual PostgreSQL booking intervals")
class HalfHourAvailabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.day = timezone.localdate() + timedelta(days=1)
        cls.court = Court.objects.create(
            name="Availability tennis court", sport="tennis", hourly_rate=Decimal("500.00"),
        )
        cls.other_court = Court.objects.create(
            name="Other tennis court", sport="tennis", hourly_rate=Decimal("500.00"),
        )
        cls.inactive_court = Court.objects.create(
            name="Inactive tennis court", sport="tennis", active=False,
        )
        cls.plan = MembershipPlan.objects.create(tier="silver", name="Availability Silver")
        cls.member = Member.objects.create(
            name="PRIVATE_AVAILABILITY_MEMBER", email="availability-private@example.com",
            phone="PRIVATE_AVAILABILITY_PHONE", plan=cls.plan,
        )

    def at(self, hour, minute=0, *, day=None):
        return timezone.make_aware(datetime.combine(day or self.day, time(hour, minute)))

    def booking(self, *, hour=9, minute=30, status="confirmed", court=None, member=False, day=None):
        return Booking.objects.create(
            court=court or self.court,
            start_datetime=self.at(hour, minute, day=day), status=status,
            booked_by_member=self.member if member else None,
            walkin_name="PRIVATE_WALKIN_NAME" if not member else "",
        )

    def response(self, route="public", **params):
        path = reverse("club:public_availability") if route == "public" else reverse(
            "club:sport_detail", args=["tennis"],
        )
        return self.client.get(path, {"date": self.day.isoformat(), **params})

    def statuses(self, response, *, route="public", court=None):
        rows = response.context["court_grid" if route == "public" else "court_slots"]
        row = next(row for row in rows if row["court"].pk == (court or self.court).pk)
        return {label: payload["status"] for label, payload in row["slots"]}

    def test_half_hour_booking_blocks_every_overlapping_sixty_minute_start(self):
        self.booking()
        for route in ["public", "sport"]:
            with self.subTest(route=route):
                response = self.response(route)
                self.assertEqual(response.status_code, 200)
                states = self.statuses(response, route=route)
                for label in ["09:00", "09:30", "10:00"]:
                    self.assertEqual(states[label], "booked")
                for label in ["08:30", "10:30"]:
                    self.assertEqual(states[label], "free")

    def test_all_slot_labels_fit_a_full_session_before_closing(self):
        response = self.response()
        labels = response.context["operating_hours"]
        self.assertEqual(len(labels), 31)
        self.assertEqual(labels[0], "06:00")
        self.assertEqual(labels[-1], "21:00")
        self.assertIn("06:30", labels)
        self.assertNotIn("21:30", labels)
        self.assertContains(response, "repeat(31, minmax(68px, 1fr))")
        self.assertContains(response, f"start={self.day.isoformat()}T09:30")

    def test_cancelling_confirmed_booking_releases_every_reserved_candidate(self):
        booking = self.booking()
        self.assertEqual(self.statuses(self.response())["10:00"], "booked")
        booking.status = "cancelled"
        booking.save()
        for route in ["public", "sport"]:
            response = self.response(route)
            self.assertTrue(all(state == "free" for state in self.statuses(response, route=route).values()))

    def test_draft_and_cancelled_bookings_do_not_reserve_slots(self):
        self.booking(hour=9, status="draft")
        self.booking(hour=12, status="cancelled")
        response = self.response()
        self.assertTrue(all(state == "free" for state in self.statuses(response).values()))
        self.assertEqual(response.context["total_confirmed_today"], 0)

    def test_other_courts_and_dates_do_not_leak_reserved_status(self):
        self.booking()
        self.booking(hour=12, day=self.day + timedelta(days=1))
        response = self.response()
        self.assertEqual(self.statuses(response, court=self.other_court)["09:30"], "free")
        self.assertEqual(self.statuses(response)["12:00"], "free")
        self.assertEqual(response.context["total_confirmed_today"], 1)
        self.assertNotIn(self.inactive_court.pk, {court.pk for court in response.context["courts"]})

    def test_exact_session_end_is_available_and_close_boundary_is_checked(self):
        self.booking(hour=20, minute=30)
        response = self.response()
        states = self.statuses(response)
        self.assertEqual(states["19:30"], "free")
        self.assertEqual(states["20:00"], "booked")
        self.assertEqual(states["20:30"], "booked")
        self.assertEqual(states["21:00"], "booked")

    def test_grid_queries_cross_midnight_intervals_by_overlap(self):
        # The shared query must include an interval that began before the local
        # date; it must not be limited to bookings whose start is on that date.
        self.booking(hour=23, minute=30, day=self.day - timedelta(days=1))
        labels, rows, count = availability_grid([self.court], self.day)
        self.assertEqual(count, 1)
        self.assertEqual(labels[0], "06:00")
        self.assertTrue(all(slot["status"] == "free" for _, slot in rows[0]["slots"]))

    def test_public_pages_and_grid_payload_do_not_include_private_booking_identity(self):
        self.booking(member=True)
        self.booking(hour=12)
        for route in ["public", "sport"]:
            response = self.response(route)
            for private_value in [self.member.name, self.member.email, self.member.phone, "PRIVATE_WALKIN_NAME"]:
                self.assertNotContains(response, private_value)
            rows = response.context["court_grid" if route == "public" else "court_slots"]
            for row in rows:
                for _, payload in row["slots"]:
                    self.assertEqual(set(payload), {"status"})

    def test_invalid_court_filter_returns_controlled_404(self):
        for value in ["unknown", "-1", "0", "1.5", "9223372036854775808", "9" * 100]:
            with self.subTest(court=value):
                response = self.response(court=value)
                self.assertEqual(response.status_code, 404)

    def test_invalid_date_defaults_to_today_without_exception(self):
        for value in ["not-a-date", "2026-13-90", "9999-12-31"]:
            with self.subTest(date=value):
                response = self.client.get(reverse("club:public_availability"), {"date": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["selected_date"], timezone.localdate())

    def test_sport_without_configured_facilities_remains_honest_empty_state(self):
        response = self.client.get(reverse("club:sport_detail", args=["swimming"]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["has_facilities"])
        self.assertEqual(response.context["court_slots"], [])
        self.assertContains(response, "No facilities or availability configured")
        self.assertNotContains(response, "Active facilities are currently available for Tennis, Badminton, Squash, and Cricket")

    def test_activity_lookup_is_case_insensitive_but_queries_canonical_sport(self):
        response = self.client.get(reverse("club:sport_detail", args=["TENNIS"]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_facilities"])
        self.assertEqual({court.pk for court in response.context["courts"]}, {self.court.pk, self.other_court.pk})
