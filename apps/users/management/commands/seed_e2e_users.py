"""
seed_e2e_users — one user per role for the Playwright browser tests (test plan R8).

    DJANGO_SETTINGS_MODULE=config.settings_e2e python manage.py seed_e2e_users

Runs ONLY under config.settings_e2e (its own database, no SOFTECH, no sends): the usernames,
the shared test password and the test branch come from that settings module. Idempotent: an
existing e2e user gets its role, branch and password reset. Also seeds the role matrix
(seed_permissions), so the menu and the API answer as they do in production, plus the
minimal fixtures the flows need (E2E_BRANCHES, E2E_ITEMS).
"""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create one test user per role in the e2e database (config.settings_e2e only)'

    def handle(self, *args, **options):
        if not getattr(settings, 'E2E_SETTINGS', False):
            raise CommandError('seed_e2e_users runs only with DJANGO_SETTINGS_MODULE=config.settings_e2e')
        if settings.WRITER_INSTANCE or not settings.SOFTECH_READ_ONLY:
            raise CommandError('refusing: the e2e settings must be a reader copy')

        from django.contrib.auth.models import User
        from apps.branches.models import Branch
        from apps.users.models import StaffProfile

        call_command('seed_permissions', verbosity=0)

        from apps.catalog.models import Item

        branches = []
        for b in settings.E2E_BRANCHES:
            br, _ = Branch.objects.update_or_create(
                softech_branch_id=b['softech_branch_id'],
                defaults={'code': b['code'], 'name': b['name'], 'name_ar': b['name'],
                          'kind': Branch.KIND_RETAIL, 'pos_enabled': True,
                          'is_active': True, 'is_operational': True},
            )
            branches.append(br)
        branch = branches[0]
        from apps.catalog.search_index import search_name_for
        for it in settings.E2E_ITEMS:
            item, _ = Item.objects.update_or_create(softech_id=it['softech_id'], defaults={
                k: v for k, v in it.items() if k != 'softech_id'})
            item.search_name = search_name_for(item)
            item.save(update_fields=['search_name'])
        # A tiny chart of accounts for the finance ledger flow (codes finance does not use).
        from apps.finance.models import GLAccount, GLAccountGroup
        for name, section, code, acc_name, nature, acc_type in settings.E2E_GL_ACCOUNTS:
            group, _ = GLAccountGroup.objects.get_or_create(name=name, defaults={'section': section})
            GLAccount.objects.update_or_create(code=code, defaults={
                'name': acc_name, 'group': group, 'nature': nature, 'account_type': acc_type})
        for role, username in settings.E2E_USERS.items():
            user, _ = User.objects.get_or_create(username=username)
            user.first_name = 'E2E'
            user.last_name = role
            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            user.set_password(settings.E2E_PASSWORD)
            user.save()
            profile, _ = StaffProfile.objects.get_or_create(user=user)
            profile.role = role
            profile.branch = branch
            profile.is_active = True
            profile.save()
        self.stdout.write(self.style.SUCCESS(
            f'[OK] {len(settings.E2E_USERS)} e2e users ready in {settings.DATABASES["default"]["NAME"]}'))
