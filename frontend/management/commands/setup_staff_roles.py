"""Repeatable Django Groups setup without assigning or replacing user accounts."""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


ROLE_PERMISSIONS = {
    'Owner': {
        'club': ('view_member', 'add_member', 'change_member', 'view_membershipplan', 'add_membershipplan',
                 'change_membershipplan', 'add_memberplanchange', 'view_booking', 'add_booking',
                 'change_booking', 'add_bookingparticipant', 'view_court'),
        'commerce': ('view_product', 'add_product', 'change_product', 'view_sale', 'add_sale', 'change_sale'),
    },
    'Reception': {
        'club': ('view_member', 'add_member', 'change_member', 'view_membershipplan', 'add_memberplanchange',
                 'view_booking', 'add_booking', 'change_booking', 'add_bookingparticipant', 'view_court'),
    },
    'Counter': {
        'commerce': ('view_product', 'view_sale', 'add_sale', 'change_sale'),
    },
}


class Command(BaseCommand):
    help = 'Create Owner, Reception and Counter roles without modifying existing users or permissions.'

    @transaction.atomic
    def handle(self, *args, **options):
        for role, applications in ROLE_PERMISSIONS.items():
            group, _ = Group.objects.get_or_create(name=role)
            permissions = []
            for app_label, codenames in applications.items():
                for codename in codenames:
                    try:
                        permissions.append(Permission.objects.get(content_type__app_label=app_label, codename=codename))
                    except Permission.DoesNotExist as error:
                        raise CommandError(f'Missing {app_label}.{codename}; apply the existing migrations first.') from error
            group.permissions.add(*permissions)
            self.stdout.write(self.style.SUCCESS(f'{role}: ensured {len(permissions)} permissions; no users changed.'))
