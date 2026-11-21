"""Explicit, atomic scheduling of shared membership-plan transitions."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Member, MemberPlanChange, MembershipPlan


def change_membership_plan(*, member_id, plan_id, effective_date, notes=''):
    if type(effective_date) is not date or effective_date < timezone.localdate():
        raise ValidationError({'effective_date': 'Choose today or a future effective date.'})
    with transaction.atomic():
        member = Member.objects.select_for_update().get(pk=member_id)
        plan = MembershipPlan.objects.select_for_update().get(pk=plan_id)
        if not plan.active:
            raise ValidationError({'new_plan': 'Choose an active membership plan.'})
        plan.full_clean()
        if member.plan_changes.filter(effective_date=effective_date).exists():
            raise ValidationError({'effective_date': 'This member already has a plan change on that date.'})
        if member.membership_end and effective_date > member.membership_end:
            raise ValidationError({'effective_date': 'The change must be within the membership period. Renew the member first.'})
        if member.membership_start and effective_date < member.membership_start:
            raise ValidationError({'effective_date': 'The change cannot begin before this membership starts.'})
        change = MemberPlanChange(member=member, plan=plan, effective_date=effective_date, notes=notes)
        change.full_clean()
        change.save()
        return change
