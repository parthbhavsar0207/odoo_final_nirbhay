"""
Club Models - Memberships, Courts, Bookings, and Booking Participants
Owned by Nayan (Backend: Membership and Bookings)
"""

from decimal import Decimal
from datetime import timedelta, datetime, time
import zoneinfo

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint
from psycopg.types.range import Range


class MembershipPlan(models.Model):
    """
    Membership plans defining tier benefits, court entitlement rates, and commerce discounts.
    """
    TIER_CHOICES = [
        ('gold', 'Gold'),
        ('silver', 'Silver'),
        ('junior', 'Junior'),
        ('platinum', 'Platinum'),
        ('corporate', 'Corporate'),
        ('weekend', 'Weekend'),
        ('custom', 'Custom'),
    ]

    tier = models.CharField(max_length=20, choices=TIER_CHOICES, unique=True)
    name = models.CharField(max_length=100)
    membership_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Membership enrollment/annual fee"
    )
    court_hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Plan-specific hourly rate for court bookings (0.00 if included/free)"
    )
    shop_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Discount percentage applicable in Club Shop"
    )
    bar_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Discount percentage applicable in Club Bar"
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['tier']
        verbose_name = 'Membership Plan'
        verbose_name_plural = 'Membership Plans'

    def __str__(self):
        return f"{self.name} ({self.get_tier_display()})"


class Member(models.Model):
    """
    Single unified member record for bookings and commerce.
    Utkarsh's commerce models reference this Member record.
    """
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    contact_details = models.TextField(blank=True, help_text="Additional contact details or address")
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )
    membership_start = models.DateField(null=True, blank=True)
    membership_end = models.DateField(null=True, blank=True)
    is_club_member = models.BooleanField(default=True)
    is_suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Member'
        verbose_name_plural = 'Members'

    def __str__(self):
        plan = self.current_plan
        tier_label = plan.get_tier_display() if plan else 'No Plan'
        return f"{self.name} [{tier_label}]"

    def effective_plan_on_date(self, target_date):
        """Resolve recorded plan changes without rewriting membership dates."""
        if self.pk:
            change = self.plan_changes.filter(effective_date__lte=target_date).select_related('plan').order_by('-effective_date', '-pk').first()
            if change is not None:
                return change.plan
        return self.plan

    @property
    def current_plan(self):
        return self.effective_plan_on_date(timezone.localdate())

    @property
    def pending_plan_changes(self):
        return self.plan_changes.filter(effective_date__gt=timezone.localdate()).select_related('plan').order_by('effective_date', 'pk')

    def is_active_on_date(self, target_date):
        """
        Checks whether membership is active on target_date:
        Must not be suspended, and target_date must be within membership_start and membership_end.
        """
        if self.is_suspended:
            return False
        if self.membership_start and self.membership_start > target_date:
            return False
        if self.membership_end and self.membership_end < target_date:
            return False
        return True

    @property
    def is_active_member(self):
        """Derives membership validity from suspension status and start/end dates."""
        return self.is_active_on_date(timezone.localdate())

    @property
    def status_label(self):
        if self.is_suspended:
            return "Suspended"
        today = timezone.localdate()
        if self.membership_end and self.membership_end < today:
            return "Expired"
        if self.membership_start and self.membership_start > today:
            return "Pending"
        return "Active"


class Court(models.Model):
    """
    Club court facility for bookings.
    """
    SPORT_CHOICES = [
        ('tennis', 'Tennis'),
        ('badminton', 'Badminton'),
        ('squash', 'Squash'),
        ('cricket', 'Cricket'),
        ('football', 'Football'),
        ('basketball', 'Basketball'),
        ('volleyball', 'Volleyball'),
        ('table_tennis', 'Table Tennis'),
        ('pickleball', 'Pickleball'),
        ('swimming', 'Swimming'),
    ]

    name = models.CharField(max_length=100, unique=True)
    sport = models.CharField(max_length=50, choices=SPORT_CHOICES, default='tennis')
    capacity = models.PositiveIntegerField(default=4)
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Standard walk-in / non-member hourly rate"
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Court'
        verbose_name_plural = 'Courts'

    @property
    def image_filename(self):
        """Map court sport to static image filename."""
        sport_map = {
            'tennis': 'images/courts/tennis.jpg',
            'badminton': 'images/courts/badminton.jpg',
            'squash': 'images/courts/squash.jpg',
            'cricket': 'images/courts/cricket.jpg',
        }
        return sport_map.get(self.sport, 'images/courts/tennis.jpg')

    def __str__(self):
        return f"{self.name} ({self.get_sport_display()})"


class MemberPlanChange(models.Model):
    """A dated plan assignment; transaction amounts remain their own snapshots."""
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='plan_changes')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name='member_changes')
    effective_date = models.DateField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['effective_date', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['member', 'effective_date'], name='club_member_plan_change_date_unique'),
        ]


class Booking(models.Model):
    """
    Court reservation model with GiST overlap exclusion constraint and daily play limits.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ]

    TYPE_CHOICES = [
        ('standard', 'Standard Play'),
        ('social', 'Social Play'),
    ]

    class PaymentMethod(models.TextChoices):
        UPI = 'upi', 'UPI / QR Code'
        CARD = 'card', 'Credit / Debit Card'
        CASH = 'cash', 'Cash (Front Desk)'
        MEMBER_TAB = 'member_tab', 'Member Account / Plan Tab'

    class PaymentStatus(models.TextChoices):
        PAID = 'paid', 'Paid'
        PENDING = 'pending', 'Pending / Pay at Venue'
        WAIVED = 'waived', 'Waived (Plan Included)'

    court = models.ForeignKey(Court, on_delete=models.PROTECT, related_name='bookings')
    booked_by_member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
        help_text="Primary booking member (null for walk-in players)"
    )
    walkin_name = models.CharField(max_length=150, blank=True, help_text="Walk-in guest name if no member record")
    walkin_contact = models.CharField(max_length=100, blank=True)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(blank=True)
    slot_range = DateTimeRangeField(blank=True, null=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    booking_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='standard')
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Snapshotted booking fee at confirmation"
    )
    currency = models.CharField(max_length=10, default='INR')
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.UPI,
        help_text="Payment method selected at booking"
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PAID,
        help_text="Settlement status of court booking fee"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_datetime']
        verbose_name = 'Booking'
        verbose_name_plural = 'Bookings'
        constraints = [
            # PostgreSQL GiST exclusion constraint:
            # Prevents overlapping confirmed bookings for the same court.
            # Cancelled and draft bookings are excluded and do not block the slot.
            ExclusionConstraint(
                name='exclude_overlapping_confirmed_bookings',
                expressions=[
                    ('court', RangeOperators.EQUAL),
                    ('slot_range', RangeOperators.OVERLAPS),
                ],
                condition=models.Q(status='confirmed'),
            )
        ]

    def __str__(self):
        player = self.booked_by_member.name if self.booked_by_member else (self.walkin_name or "Walk-in")
        return f"{self.court.name} | {self.start_datetime.strftime('%Y-%m-%d %H:%M')} | {player} ({self.get_status_display()})"

    @classmethod
    def count_member_daily_plays(cls, member, booking_date, exclude_booking_id=None):
        """
        Counts distinct confirmed bookings on booking_date (Asia/Kolkata)
        where member participates as primary booker OR as a participant in BookingParticipant.
        Each booking is counted at most once per member.
        """
        tz = timezone.get_current_timezone()
        day_start = timezone.make_aware(datetime.combine(booking_date, time.min), tz)
        day_end = timezone.make_aware(datetime.combine(booking_date, time.max), tz)

        qs = cls.objects.filter(
            status='confirmed',
            start_datetime__gte=day_start,
            start_datetime__lte=day_end
        )
        if exclude_booking_id:
            qs = qs.exclude(pk=exclude_booking_id)

        return qs.filter(
            models.Q(booked_by_member=member) |
            models.Q(participants__member=member)
        ).distinct().count()

    def calculate_price(self):
        """
        Calculates the applicable booking rate from member plan or court standard rate.

        Rules:
        1. A member gets their plan's court rate ONLY when their membership dates
           include the booking date and they are not suspended.
        2. An expired or suspended profile may still be used to book at the normal
           walk-in court rate; retains the member link for club history, but does
           not apply member pricing or plan benefits.
        3. A booking without a member profile (walk-in) also uses the normal
           walk-in court rate.
        """
        tz = timezone.get_current_timezone()
        booking_date = (
            timezone.localtime(self.start_datetime, tz).date()
            if self.start_datetime
            else timezone.localdate()
        )

        plan = self.booked_by_member.effective_plan_on_date(booking_date) if self.booked_by_member else None
        # Apply the plan effective for this date only for eligible members.
        if (
            self.booked_by_member
            and self.booked_by_member.is_club_member
            and plan
            and plan.active
            and self.booked_by_member.is_active_on_date(booking_date)
        ):
            return plan.court_hourly_rate
        elif self.court:
            return self.court.hourly_rate
        return Decimal('0.00')

    def snapshot_price(self):
        """
        Snapshots the booking price at confirmation based on court and member plan rates.
        Price becomes an immutable historical snapshot once confirmed.
        """
        if self.status == 'confirmed':
            self.price = self.calculate_price()
        return self.price

    def clean(self):
        """
        Enforces business rules:
        1. Sessions last exactly 60 minutes.
        2. Slots start on the hour or half-hour in Asia/Kolkata timezone.
        3. No confirmed bookings can overlap on the same court.
        4. Members can participate in at most two confirmed bookings per club-local date.
        """
        tz = timezone.get_current_timezone()

        if self.start_datetime:
            local_start = timezone.localtime(self.start_datetime, tz)
            if local_start.minute not in (0, 30) or local_start.second or local_start.microsecond:
                raise ValidationError({'start_datetime': 'Sessions must start on the hour or half-hour.'})

        # Auto-compute 60-minute duration if end_datetime is not explicitly supplied
        if self.start_datetime and not self.end_datetime:
            self.end_datetime = self.start_datetime + timedelta(minutes=60)

        if self.start_datetime:
            # 2. Slot minute alignment: bookings must start on the hour or half-hour
            local_start = timezone.localtime(self.start_datetime, tz)
            if local_start.minute not in (0, 30) or local_start.second != 0:
                raise ValidationError({
                    'start_datetime': "Bookings must start on the hour (e.g. 10:00) or half-hour (e.g. 10:30)."
                })

        if self.start_datetime and self.end_datetime:
            # 1. 60-minute session duration
            duration = self.end_datetime - self.start_datetime
            if duration != timedelta(minutes=60):
                raise ValidationError({
                    'end_datetime': f"Sessions must last exactly 60 minutes. Current duration: {duration.total_seconds() / 60:.0f} minutes."
                })

            # Update slot_range for Postgres GiST constraint
            self.slot_range = Range(self.start_datetime, self.end_datetime, bounds='[)')

        # Business validations when booking is confirmed
        if self.status == 'confirmed' and self.court_id and self.start_datetime and self.end_datetime:
            # 3. Application-level overlap check (convenience check before database constraint)
            overlap_qs = Booking.objects.filter(
                court=self.court,
                status='confirmed',
                start_datetime__lt=self.end_datetime,
                end_datetime__gt=self.start_datetime
            )
            if self.pk:
                overlap_qs = overlap_qs.exclude(pk=self.pk)

            if overlap_qs.exists():
                raise ValidationError(
                    f"Court '{self.court.name}' is already confirmed for another booking during this time slot."
                )

            # 4. Daily limit check: max 2 confirmed bookings per member per local club date
            member_ids = set()
            if self.booked_by_member_id:
                member_ids.add(self.booked_by_member_id)
            if self.pk:
                member_ids.update(self.participants.filter(member__isnull=False).values_list('member_id', flat=True))
            local_date = timezone.localtime(self.start_datetime, tz).date()
            for member in Member.objects.filter(pk__in=member_ids).order_by('pk'):
                member_bookings_count = self.count_member_daily_plays(
                    member,
                    local_date,
                    exclude_booking_id=self.pk
                )

                if member_bookings_count >= 2:
                    raise ValidationError(
                        f"Member '{member.name}' already has {member_bookings_count} confirmed "
                        f"bookings on {local_date}. Maximum allowed is 2 per club day."
                    )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            # Existing parent first, then member IDs in one consistent order.
            # All booking/roster saves use these locks before counting plays.
            persisted = type(self).objects.select_for_update().filter(pk=self.pk).first() if self.pk else None
            member_ids = {value for value in (self.booked_by_member_id, persisted.booked_by_member_id if persisted else None) if value}
            if persisted:
                member_ids.update(self.participants.filter(member__isnull=False).values_list('member_id', flat=True))
            list(Member.objects.select_for_update().filter(pk__in=member_ids).order_by('pk'))
            if self.start_datetime and not self.end_datetime:
                self.end_datetime = self.start_datetime + timedelta(minutes=60)
            if self.start_datetime and self.end_datetime:
                self.slot_range = Range(self.start_datetime, self.end_datetime, bounds='[)')

            # A zero-price confirmed booking is still a saved historical snapshot.
            if self.status == 'confirmed' and not (persisted and persisted.status == 'confirmed'):
                self.snapshot_price()

            # Auto-set payment_status if waived under a free court plan
            if self.price == Decimal('0.00') and self.booked_by_member:
                self.payment_status = self.PaymentStatus.WAIVED
                if self.payment_method == self.PaymentMethod.CASH:
                    self.payment_method = self.PaymentMethod.MEMBER_TAB

            self.full_clean()
            super().save(*args, **kwargs)

            # The booking and its primary participant succeed or roll back together.
            if self.booked_by_member_id:
                BookingParticipant.objects.get_or_create(
                    booking=self,
                    member_id=self.booked_by_member_id,
                )


class BookingParticipant(models.Model):
    """
    Participants in a booking (both registered members and optional guests).
    Enables counting social play bookings toward each member's 2-per-day limit.
    """
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='participants')
    member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='participations'
    )
    guest_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Booking Participant'
        verbose_name_plural = 'Booking Participants'
        constraints = [
            # A member should only be listed once per booking
            models.UniqueConstraint(
                fields=['booking', 'member'],
                condition=models.Q(member__isnull=False),
                name='unique_member_participant_per_booking'
            )
        ]

    def __str__(self):
        name = self.member.name if self.member else (self.guest_name or "Guest")
        return f"{name} (Booking #{self.booking_id})"

    def clean(self):
        """
        Validates daily limit for participant members on confirmed bookings.
        Counts each distinct booking once per member across primary booker and participant roster.
        """
        if self.member and self.booking_id and hasattr(self, 'booking') and self.booking.status == 'confirmed':
            tz = timezone.get_current_timezone()
            local_date = timezone.localtime(self.booking.start_datetime, tz).date()
            member_bookings_count = Booking.count_member_daily_plays(
                self.member,
                local_date,
                exclude_booking_id=self.booking.pk
            )

            if member_bookings_count >= 2:
                raise ValidationError(
                    f"Member '{self.member.name}' has already reached the maximum of 2 confirmed bookings on {local_date}."
                )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            # Re-read the locked parent so a stale draft cannot bypass a newly
            # confirmed booking's daily limit. Match Booking.save's lock order.
            self.booking = Booking.objects.select_for_update().get(pk=self.booking_id)
            member_ids = {value for value in (self.member_id, self.booking.booked_by_member_id) if value}
            list(Member.objects.select_for_update().filter(pk__in=member_ids).order_by('pk'))
            self.full_clean()
            super().save(*args, **kwargs)
