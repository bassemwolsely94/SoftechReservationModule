"""
apps/users/management/commands/set_admin.py

Usage:
    python manage.py set_admin bassemwolsely94
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create or update StaffProfile for a user and set role to admin'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)
        parser.add_argument('--role', type=str, default='admin')

    def handle(self, *args, **options):
        from django.contrib.auth.models import User
        from apps.users.models import StaffProfile

        username = options['username']
        role     = options['role']

        # List all users if not found
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User "{username}" not found.'))
            self.stdout.write('Available users:')
            for u in User.objects.all():
                self.stdout.write(f'  - {u.username} (id={u.id})')
            return

        profile, created = StaffProfile.objects.get_or_create(user=user)
        profile.role = role
        profile.save()

        self.stdout.write(self.style.SUCCESS(
            f'✅ {"Created" if created else "Updated"} StaffProfile for '
            f'"{username}" — role={profile.role}'
        ))
