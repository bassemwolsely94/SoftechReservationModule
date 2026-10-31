"""Lift a login lock from the server shell — for when every admin is locked out (N0/H8).

    manage.py unlock_login <username | softech_user_id | softech_username>
"""
from django.core.management.base import BaseCommand, CommandError

from apps.users import lockout
from apps.users.models import StaffProfile
from apps.users.views import _resolve_user


class Command(BaseCommand):
    help = 'Lift the login lock of one account (resolved like the login screen does).'

    def add_arguments(self, parser):
        parser.add_argument('identifier')

    def handle(self, *args, identifier, **opts):
        user = _resolve_user(identifier)
        profile = StaffProfile.objects.filter(user=user).select_related('user').first() if user else None
        if not profile:
            raise CommandError(f'No account found for "{identifier}"')
        lockout.unlock(profile, None, None)
        self.stdout.write(self.style.SUCCESS(
            f'Login lock lifted for {profile.full_name or profile.user.username}'))
