"""Lift a bulk-read temporary block early (N5): manage.py clear_bulk_block <username>."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
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
        was = cache.get(f'access:bulkblock:{user.pk}') is not None
        cache.delete(f'access:bulkblock:{user.pk}')
        write_access_audit('bulk_read_alert', user.pk, 'block cleared by command',
                           {'cleared': True, 'was_blocked': was, 'username': user.get_username()},
                           label='bulk read')
        self.stdout.write(f'bulk-read block cleared for {user.get_username()} (was blocked: {was})')
