"""Member directory reflects effective benefits and future assignments."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from club.models import Member, MemberPlanChange, MembershipPlan
from frontend.tests.helpers import login_test_staff


class MemberDirectoryTests(TestCase):
    def setUp(self):
        super().setUp()
        login_test_staff(self.client)

    def test_active_filter_and_count_match_current_plan_eligibility(self):
        today = timezone.localdate()
        active = MembershipPlan.objects.create(tier="silver", name="Active Silver")
        inactive = MembershipPlan.objects.create(tier="gold", name="Inactive Gold", active=False)
        eligible = Member.objects.create(name="Eligible", plan=active)
        transitioned = Member.objects.create(name="Transitioned", plan=inactive)
        MemberPlanChange.objects.create(member=transitioned, plan=active, effective_date=today)
        for values in [
            {"name": "Guest", "is_club_member": False, "plan": active},
            {"name": "No Plan"},
            {"name": "Inactive Plan", "plan": inactive},
            {"name": "Suspended", "plan": active, "is_suspended": True},
            {"name": "Expired", "plan": active, "membership_end": today - timedelta(days=1)},
            {"name": "Future", "plan": active, "membership_start": today + timedelta(days=1)},
        ]:
            Member.objects.create(**values)
        response = self.client.get(reverse("club:member_list"), {"status": "active"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_count"], 2)
        self.assertEqual({member.pk for member in response.context["members"]}, {eligible.pk, transitioned.pk})

    def test_pending_assignment_visible_when_member_has_no_baseline_plan(self):
        plan = MembershipPlan.objects.create(tier="silver", name="Future Silver")
        member = Member.objects.create(name="Awaiting Plan")
        MemberPlanChange.objects.create(
            member=member, plan=plan, effective_date=timezone.localdate() + timedelta(days=1),
        )
        response = self.client.get(reverse("club:member_list"))
        self.assertContains(response, "Future Silver from")
        self.assertIsNone(member.current_plan)
