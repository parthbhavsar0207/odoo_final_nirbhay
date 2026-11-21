"""
Management command to seed initial membership plans, courts, and demo members.
All pricing and fee values here are strictly ILLUSTRATIVE DEMO DATA for development and integration.
Usage: python manage.py seed_club_data
"""

from decimal import Decimal
from datetime import date
from django.core.management.base import BaseCommand
from club.models import MembershipPlan, Court, Member


class Command(BaseCommand):
    help = "Seeds initial Gold, Silver, Junior plans, courts, and demo members (idempotent; illustrative demo data)."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            "[DEMO DATA] Note: Seeded membership fees, court hourly rates, and discounts are "
            "illustrative demo placeholders for development/testing, not actual club prices."
        ))

        # 1. Membership Plans (Stable identifier: 'tier')
        plans_data = [
            {
                'tier': 'gold',
                'name': 'Gold Plan',
                'membership_fee': Decimal('5000.00'),      # Illustrative demo fee
                'court_hourly_rate': Decimal('0.00'),       # Free court play for Gold
                'shop_discount_percent': Decimal('20.00'),  # Illustrative 20% shop discount
                'bar_discount_percent': Decimal('15.00'),   # Illustrative 15% bar discount
                'active': True,
            },
            {
                'tier': 'silver',
                'name': 'Silver Plan',
                'membership_fee': Decimal('3000.00'),      # Illustrative demo fee
                'court_hourly_rate': Decimal('200.00'),     # Illustrative discounted court rate
                'shop_discount_percent': Decimal('10.00'),  # Illustrative 10% shop discount
                'bar_discount_percent': Decimal('5.00'),    # Illustrative 5% bar discount
                'active': True,
            },
            {
                'tier': 'junior',
                'name': 'Junior Plan',
                'membership_fee': Decimal('1500.00'),      # Illustrative demo fee
                'court_hourly_rate': Decimal('150.00'),     # Illustrative junior court rate
                'shop_discount_percent': Decimal('15.00'),  # Illustrative 15% shop discount
                'bar_discount_percent': Decimal('0.00'),    # No bar discount for juniors
                'active': True,
            },
        ]

        plans = {}
        plan_created_cnt = 0
        plan_updated_cnt = 0
        for pdata in plans_data:
            plan, created = MembershipPlan.objects.update_or_create(
                tier=pdata['tier'],
                defaults=pdata
            )
            plans[plan.tier] = plan
            if created:
                plan_created_cnt += 1
            else:
                plan_updated_cnt += 1

        self.stdout.write(f"Plans: {plan_created_cnt} created, {plan_updated_cnt} updated (Total: {MembershipPlan.objects.count()})")

        # 2. Courts (Stable identifier: 'name' - aligned with Champions Club sports brief)
        courts_data = [
            {'name': 'Court 1 (Tennis - Clay)', 'sport': 'tennis', 'capacity': 4, 'hourly_rate': Decimal('500.00')},
            {'name': 'Court 2 (Tennis - Hard)', 'sport': 'tennis', 'capacity': 4, 'hourly_rate': Decimal('500.00')},
            {'name': 'Court 3 (Badminton - Indoor)', 'sport': 'badminton', 'capacity': 4, 'hourly_rate': Decimal('300.00')},
            {'name': 'Court 4 (Squash - Glass Back)', 'sport': 'squash', 'capacity': 2, 'hourly_rate': Decimal('400.00')},
            {'name': 'Net 1 (Cricket - Practice Turf)', 'sport': 'cricket', 'capacity': 6, 'hourly_rate': Decimal('600.00')},
        ]

        court_created_cnt = 0
        court_updated_cnt = 0
        for cdata in courts_data:
            court, created = Court.objects.update_or_create(
                name=cdata['name'],
                defaults=cdata
            )
            if created:
                court_created_cnt += 1
            else:
                court_updated_cnt += 1

        self.stdout.write(f"Courts: {court_created_cnt} created, {court_updated_cnt} updated (Total: {Court.objects.count()})")

        # 3. Demo Members (Stable identifier: 'email')
        # Covers active tiers, expired profile, and suspended profile
        members_data = [
            {
                'name': 'Aarav Sharma',
                'email': 'aarav.sharma@example.com',
                'phone': '+91 9820011223',
                'plan': plans['gold'],
                'membership_start': date(2026, 1, 1),
                'membership_end': date(2026, 12, 31),
                'is_club_member': True,
                'is_suspended': False,
            },
            {
                'name': 'Rohan Patel',
                'email': 'rohan.patel@example.com',
                'phone': '+91 9820033445',
                'plan': plans['silver'],
                'membership_start': date(2026, 1, 1),
                'membership_end': date(2026, 12, 31),
                'is_club_member': True,
                'is_suspended': False,
            },
            {
                'name': 'Vivaan Mehta',
                'email': 'vivaan.mehta@example.com',
                'phone': '+91 9820055667',
                'plan': plans['junior'],
                'membership_start': date(2026, 1, 1),
                'membership_end': date(2026, 12, 31),
                'is_club_member': True,
                'is_suspended': False,
            },
            {
                'name': 'Dev Kulkarni',
                'email': 'dev.kulkarni@example.com',
                'phone': '+91 9820077889',
                'plan': plans['silver'],
                'membership_start': date(2025, 1, 1),
                'membership_end': date(2025, 12, 31),  # Expired membership
                'is_club_member': True,
                'is_suspended': False,
            },
            {
                'name': 'Pooja Reddy',
                'email': 'pooja.reddy@example.com',
                'phone': '+91 9820099001',
                'plan': plans['gold'],
                'membership_start': date(2026, 1, 1),
                'membership_end': date(2026, 12, 31),
                'is_club_member': True,
                'is_suspended': True,  # Suspended profile
            },
        ]

        member_created_cnt = 0
        member_updated_cnt = 0
        for mdata in members_data:
            member, created = Member.objects.update_or_create(
                email=mdata['email'],
                defaults=mdata
            )
            if created:
                member_created_cnt += 1
            else:
                member_updated_cnt += 1

        self.stdout.write(f"Members: {member_created_cnt} created, {member_updated_cnt} updated (Total: {Member.objects.count()})")
        self.stdout.write(self.style.SUCCESS("[OK] Demo seed data successfully synced."))
