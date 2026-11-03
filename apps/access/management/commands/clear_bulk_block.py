"""Lift a bulk-read temporary block early (N5): manage.py clear_bulk_block <username>."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.access.audit import write_access_audit


class Command(BaseCommand):
    help = 'Delete the bulk-read block of a user and write an audit row.'

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, *args, **opts):
        User = get_user_model()
        try:
            user = User.objects.get(**{User.USERNAME_FIELD: opts['username']})
        except User.DoesNotExist:
            raise CommandError(f"no such user: {opts['username']}")
        from apps.users.models import StaffProfile
        profile = StaffProfile.objects.filter(user=user).first()
        if profile is None or profile.bulk_read_blocked_until is None:
            self.stdout.write(f'{user.get_username()} has no bulk-read block')
            return
        StaffProfile.objects.filter(pk=profile.pk).update(bulk_read_blocked_until=None)
        write_access_audit('bulk_read_alert', user.pk, 'block cleared by command',
                           {'cleared': True, 'was_blocked': True, 'username': user.get_username()},
                           label='bulk read')
        self.stdout.write(f'bulk-read block cleared for {user.get_username()}')
