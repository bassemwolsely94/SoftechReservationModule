"""
seed_uat_users - test users for the role-by-role UAT on the restored copy
(docs/superpowers/specs/2026-11-16-role-uat-design.md §5.1).

    . scripts/uat/uat-env.ps1
    python manage.py seed_uat_users --settings=config.settings_uat [--real-auto] [--real user ...]

Runs ONLY under config.settings_uat (a reader copy: no SOFTECH, no sends, its own database).

Creates `uat_*` users for all roles in branch A plus branch-shape users (branch-B twins,
multi-branch, restricted-branch, phone hidden / visible). `--real` / `--real-auto` take real
users of the copy and reset their password (the copy is thrown away, nothing to revert).
2FA is switched off for every listed user and enforcement is removed on the copy only - 2FA
itself is covered by the backend tests.

Never touches the role matrix (no seed_permissions): the copy's live rows are what is tested.
Credentials go to a git-ignored JSON file (frontend/uat/.uat-users.json), never to stdout.
"""
import json
import secrets
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.users.roles import ROLE_KEYS

TWIN_ROLES = ['pharmacist', 'salesperson', 'viewer', 'delivery']   # branch-scoped roles
DEFAULT_OUT = Path(settings.BASE_DIR) / 'frontend' / 'uat' / '.uat-users.json'


class Command(BaseCommand):
    help = 'Create UAT users for every role and branch shape (config.settings_uat only)'

    def add_arguments(self, parser):
        parser.add_argument('--branch-a', help='softech_branch_id of branch A (default: busiest retail branch)')
        parser.add_argument('--branch-b', help='softech_branch_id of branch B (default: second busiest)')
        parser.add_argument('--real', nargs='*', default=[], help='real usernames to include (password reset on the copy)')
        parser.add_argument('--real-auto', action='store_true',
                            help='also include, per role, the most recently active real user (last 30 days)')
        parser.add_argument('--out', default=str(DEFAULT_OUT))

    def handle(self, *args, **opts):
        if not getattr(settings, 'UAT_SETTINGS', False):
            raise CommandError('seed_uat_users runs only with config.settings_uat')
        if settings.WRITER_INSTANCE or not settings.SOFTECH_READ_ONLY:
            raise CommandError('refusing: the UAT settings must be a reader copy')

        from apps.branches.models import Branch
        from apps.users.models import StaffProfile

        branch_a, branch_b = self._branches(Branch, opts['branch_a'], opts['branch_b'])
        out = Path(opts['out'])
        password = self._password(out)

        real_names = list(opts['real'])
        if opts['real_auto']:
            real_names += [n for n in self._recent_real_users(StaffProfile, branch_a, branch_b) if n not in real_names]
        real_profiles = [self._real_profile(StaffProfile, name) for name in real_names]

        users = []
        with transaction.atomic():
            for role in ROLE_KEYS:
                users.append(self._uat_user(StaffProfile, role, role, 'home', branch_a, password))
            for role in TWIN_ROLES:
                users.append(self._uat_user(StaffProfile, f'{role}@B', role, 'twinB', branch_b, password))
            multi = self._uat_user(StaffProfile, 'multi', 'pharmacist', 'multi', branch_a, password)
            self._profile(multi).allowed_branches.set([branch_b])
            users.append(multi)
            restricted = self._uat_user(StaffProfile, 'restricted', 'supervisor', 'restricted', branch_a, password)
            self._profile(restricted).restricted_branches.set([branch_b])
            users.append(restricted)
            for key, sees in (('phoneHidden', False), ('phoneVisible', True)):
                row = self._uat_user(StaffProfile, key, 'pharmacist', key, branch_a, password)
                StaffProfile.objects.filter(user__username=row['username']).update(can_see_customer_phone=sees)
                users.append(row)
            for prof in real_profiles:
                user = prof.user
                user.set_password(password)
                user.save(update_fields=['password'])
                self._no_mfa(prof)
                users.append({'key': f'real:{user.username}', 'username': user.username, 'role': prof.role,
                              'shape': 'real', 'branch': prof.branch.softech_branch_id if prof.branch else None})
            self._mfa_enforcement_off()

        data = {
            'password': password,
            'branchA': self._branch_json(branch_a),
            'branchB': self._branch_json(branch_b),
            'users': users,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(
            f'[OK] {len(users)} UAT users ready in {settings.DATABASES["default"]["NAME"]} '
            f'(A={branch_a.softech_branch_id}, B={branch_b.softech_branch_id}, real={len(real_profiles)}); '
            f'credentials in {out.name}'))

    # ── helpers ────────────────────────────────────────────────────────────────
    def _branches(self, Branch, a, b):
        if a and b:
            try:
                return Branch.objects.get(softech_branch_id=a), Branch.objects.get(softech_branch_id=b)
            except Branch.DoesNotExist as exc:
                raise CommandError(f'branch not found: {exc}')
        since = timezone.now() - timedelta(days=30)
        busiest = list(Branch.objects.retail()
                       .annotate(n=Count('purchasehistory', filter=Q(purchasehistory__invoice_date__gte=since)))
                       .order_by('-n', 'softech_branch_id')[:2])
        if len(busiest) < 2:
            raise CommandError('need two retail branches; pass --branch-a / --branch-b')
        return busiest[0], busiest[1]

    def _password(self, out):
        if out.exists():
            try:
                return json.loads(out.read_text(encoding='utf-8'))['password']
            except (ValueError, KeyError):
                pass
        return 'Uat-' + secrets.token_urlsafe(12)

    def _uat_user(self, StaffProfile, key, role, shape, branch, password):
        username = 'uat_' + key.replace('@', '_').lower()
        user, _ = User.objects.get_or_create(username=username)
        user.first_name, user.last_name = 'UAT', key
        user.is_active, user.is_staff, user.is_superuser = True, False, False
        user.set_password(password)
        user.save()
        prof, _ = StaffProfile.objects.get_or_create(user=user)
        prof.role, prof.branch, prof.is_active = role, branch, True
        prof.access_all_branches = False
        prof.can_see_customer_phone = True
        prof.save()
        prof.allowed_branches.clear()
        prof.restricted_branches.clear()
        self._no_mfa(prof)
        return {'key': key, 'username': username, 'role': role, 'shape': shape, 'branch': branch.softech_branch_id}

    @staticmethod
    def _profile(row):
        from apps.users.models import StaffProfile
        return StaffProfile.objects.get(user__username=row['username'])

    @staticmethod
    def _no_mfa(prof):
        prof.mfa_enabled, prof.mfa_secret, prof.mfa_backup_codes, prof.mfa_confirmed_at = False, '', [], None
        prof.save(update_fields=['mfa_enabled', 'mfa_secret', 'mfa_backup_codes', 'mfa_confirmed_at'])

    @staticmethod
    def _mfa_enforcement_off():
        # Delete, do not set to false: apps/users/mfa.py reads any row as "on" (finding B-01).
        from apps.config.models import SystemSetting
        SystemSetting.objects.filter(key='security.mfa_enforced').delete()

    def _real_profile(self, StaffProfile, username):
        prof = StaffProfile.objects.select_related('user', 'branch').filter(user__username=username).first()
        if prof is None:
            raise CommandError(f'real user {username}: no such user with a staff profile')
        if not (prof.user.is_active and prof.is_active):
            raise CommandError(f'real user {username}: inactive')
        return prof

    @staticmethod
    def _recent_real_users(StaffProfile, branch_a, branch_b):
        # Activity = the latest screen view (audit ScreenView, P-57); JWT logins never update
        # auth last_login, so it is only the fallback.
        from django.db.models import Max
        from django.db.models.functions import Coalesce
        since = timezone.now() - timedelta(days=30)
        names = []
        for role in ROLE_KEYS:
            qs = (StaffProfile.objects.filter(role=role, is_active=True, user__is_active=True)
                  .exclude(user__username__startswith='uat_').exclude(user__username__startswith='e2e_')
                  .annotate(seen=Coalesce(Max('screen_views__at', filter=Q(screen_views__at__gte=since)),
                                          'user__last_login'))
                  .filter(seen__gte=since)
                  .select_related('user'))
            in_ab = qs.filter(branch__in=[branch_a, branch_b]).order_by('-seen').first()
            pick = in_ab or qs.order_by('-seen').first()
            if pick:
                names.append(pick.user.username)
        return names

    @staticmethod
    def _branch_json(b):
        return {'id': b.pk, 'code': b.softech_branch_id, 'name': b.name_ar or b.name}
