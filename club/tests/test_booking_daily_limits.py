"""Daily play limits hold across roster changes and concurrent PostgreSQL saves."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from club.models import Booking, BookingParticipant, Court, Member


class DailyLimitFixtures:
    def setUp(self):
        super().setUp()
        self.day = timezone.localdate() + timedelta(days=1)
        self.member = Member.objects.create(name="Daily limit player")
        self.courts = [
            Court.objects.create(name=f"Daily limit court {index}", sport="tennis", hourly_rate=Decimal("500.00"))
            for index in range(3)
        ]

    def at(self, hour, *, day=None):
        return timezone.make_aware(datetime.combine(day or self.day, time(hour)))

    def booking(self, hour, *, member=None, status="confirmed", court=None, day=None):
        return Booking.objects.create(
            court=court or self.courts[0], start_datetime=self.at(hour, day=day),
            booked_by_member=member, walkin_name="" if member else "Walk-in player",
            status=status, booking_type="social",
        )

    def social_play(self, hour):
        booking = self.booking(hour)
        BookingParticipant.objects.create(booking=booking, member=self.member)
        return booking


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL booking constraints and row locks")
class BookingDailyLimitTests(DailyLimitFixtures, TestCase):
    def test_primary_third_booking_is_rejected_without_partial_record(self):
        self.booking(9, member=self.member)
        self.booking(11, member=self.member)
        with self.assertRaises(ValidationError):
            self.booking(13, member=self.member)
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)
        self.assertEqual(Booking.objects.count(), 2)
        self.assertEqual(BookingParticipant.objects.count(), 2)

    def test_third_social_participant_has_visible_form_error(self):
        self.social_play(9)
        self.social_play(11)
        target = self.booking(13)
        response = self.client.post(reverse("club:booking_detail", args=[target.pk]), {
            "member": self.member.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["participant_form"].non_field_errors())
        self.assertContains(response, "maximum of 2 confirmed bookings")
        self.assertFalse(target.participants.filter(member=self.member).exists())
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)

    def test_invalid_participant_field_error_is_rendered(self):
        target = self.booking(9)
        response = self.client.post(reverse("club:booking_detail", args=[target.pk]), {
            "member": 999999,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("member", response.context["participant_form"].errors)
        self.assertContains(response, "Select a valid choice")
        self.assertEqual(target.participants.count(), 0)

    def test_confirming_draft_revalidates_every_existing_roster_member(self):
        self.social_play(9)
        self.social_play(11)
        draft = self.booking(13, status="draft")
        BookingParticipant.objects.create(booking=draft, member=self.member)
        draft.status = "confirmed"
        with self.assertRaises(ValidationError):
            draft.save()
        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)

    def test_participant_save_reloads_stale_draft_parent_before_validation(self):
        self.social_play(9)
        self.social_play(11)
        stale_draft = self.booking(13, status="draft")
        participant = BookingParticipant(booking=stale_draft, member=self.member)
        current = Booking.objects.get(pk=stale_draft.pk)
        current.status = "confirmed"
        current.save()
        with self.assertRaises(ValidationError):
            participant.save()
        self.assertFalse(current.participants.filter(member=self.member).exists())
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)

    def test_primary_participant_failure_rolls_back_booking_creation(self):
        with patch("club.models.BookingParticipant.objects.get_or_create", side_effect=ValidationError("Roster failed")):
            with self.assertRaises(ValidationError):
                self.booking(9, member=self.member)
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(BookingParticipant.objects.count(), 0)

    def test_primary_and_roster_count_once_and_cancellation_releases_capacity(self):
        first = self.booking(9, member=self.member)
        self.social_play(11)
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)
        self.assertEqual(first.participants.filter(member=self.member).count(), 1)
        first.status = "cancelled"
        first.save()
        self.booking(13, member=self.member)
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)

    def test_next_club_date_has_independent_daily_capacity(self):
        self.booking(9, member=self.member)
        self.booking(11, member=self.member)
        next_day = self.day + timedelta(days=1)
        self.booking(9, member=self.member, day=next_day)
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)
        self.assertEqual(Booking.count_member_daily_plays(self.member, next_day), 1)


@skipUnless(connection.vendor == "postgresql", "Requires real independent PostgreSQL connections")
class BookingDailyLimitConcurrencyTests(DailyLimitFixtures, TransactionTestCase):
    def run_parallel(self, operations):
        barrier = Barrier(len(operations))

        def worker(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '5s'")
                    cursor.execute("SET statement_timeout TO '10s'")
                barrier.wait(timeout=5)
                try:
                    operation()
                except ValidationError:
                    return "rejected"
                return "saved"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(worker, operation) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_primary_bookings_cannot_claim_same_last_daily_play(self):
        self.booking(9, member=self.member)
        member_id = self.member.pk

        def reserve(court_id):
            return lambda: Booking.objects.create(
                court_id=court_id, booked_by_member_id=member_id,
                start_datetime=self.at(11), status="confirmed",
            )

        results = self.run_parallel([reserve(self.courts[1].pk), reserve(self.courts[2].pk)])
        self.assertCountEqual(results, ["saved", "rejected"])
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)
        self.assertEqual(Booking.objects.count(), 2)
        self.assertEqual(BookingParticipant.objects.count(), 2)

    def test_concurrent_roster_additions_cannot_claim_same_last_daily_play(self):
        self.social_play(9)
        targets = [self.booking(11, court=self.courts[1]), self.booking(13, court=self.courts[2])]
        member_id = self.member.pk

        def add_player(booking_id):
            return lambda: BookingParticipant.objects.create(booking_id=booking_id, member_id=member_id)

        results = self.run_parallel([add_player(target.pk) for target in targets])
        self.assertCountEqual(results, ["saved", "rejected"])
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)
        self.assertEqual(BookingParticipant.objects.filter(member=self.member).count(), 2)

    def test_confirmation_racing_roster_addition_never_creates_third_daily_play(self):
        self.social_play(9)
        self.social_play(11)
        draft = self.booking(13, status="draft")
        member_id = self.member.pk
        booking_id = draft.pk

        def confirm():
            booking = Booking.objects.get(pk=booking_id)
            booking.status = "confirmed"
            booking.save()

        def add_player():
            BookingParticipant.objects.create(booking_id=booking_id, member_id=member_id)

        results = self.run_parallel([confirm, add_player])
        self.assertCountEqual(results, ["saved", "rejected"])
        self.assertEqual(Booking.count_member_daily_plays(self.member, self.day), 2)
        draft.refresh_from_db()
        self.assertFalse(draft.status == "confirmed" and draft.participants.filter(member=self.member).exists())
