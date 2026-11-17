"""
export_uat_expectations - what each UAT user SHOULD see, from the backend's own rules, for the
browser suite (docs/superpowers/specs/2026-11-16-role-uat-design.md §5.2-5.4, §7.1).

    python manage.py export_uat_expectations --settings=config.settings_uat

Reads frontend/uat/.uat-users.json (from seed_uat_users) and writes:
  * frontend/uat/.uat-expected.json (git-ignored: holds real reference phones)
      users[key]   = {perms, branchIds, allBranches, seesPhones}
      reference[A|B] = sample real records of that branch (customers with phones, reservations,
                       transfers, demand, POS orders, shortage lists, invoices)
  * docs/uat/permission-drift.md - live RoleModuleAccess rows vs the code's seed_permissions.

Nothing is re-derived: perms = effective_permissions() (what /api/users/my-permissions/ returns),
branches = core.branch_scope.branch_ids(), seesRecordPhones = access.record_phones_visible(),
seesPhones = the raw can_see_customer_phone flag (other branches are masked on top: phones_visible).
"""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

BASE = Path(settings.BASE_DIR)
SAMPLE = {'customers': 20, 'reservations': 10, 'transfers': 10, 'demand': 10, 'posOrders': 10,
          'shortage': 10, 'invoices': 10}


class Command(BaseCommand):
    help = 'Export UAT expectations + permission drift (config.settings_uat only)'

    def add_arguments(self, parser):
        parser.add_argument('--users', default=str(BASE / 'frontend' / 'uat' / '.uat-users.json'))
        parser.add_argument('--out', default=str(BASE / 'frontend' / 'uat' / '.uat-expected.json'))
        parser.add_argument('--drift', default=str(BASE / 'docs' / 'uat' / 'permission-drift.md'))

    def handle(self, *args, **opts):
        if not getattr(settings, 'UAT_SETTINGS', False):
            raise CommandError('export_uat_expectations runs only with config.settings_uat')
        src = Path(opts['users'])
        if not src.exists():
            raise CommandError(f'{src} not found: run seed_uat_users first')
        seeded = json.loads(src.read_text(encoding='utf-8'))

        from core import branch_scope
        from apps.users.views import effective_permissions
        from apps.customers import access

        users = {}
        for row in seeded['users']:
            user = User.objects.select_related('staff_profile').get(username=row['username'])
            profile = user.staff_profile
            ids = branch_scope.branch_ids(user)
            users[row['key']] = {
                'username': row['username'],
                'role': profile.role,
                'perms': effective_permissions(user)[1],
                'allBranches': ids is None,
                'branchIds': sorted(ids) if ids is not None else [],
                # the raw flag, and the backend's record rule (flag AND not the viewer role, D3/D4);
                # another branch's customer is masked on top of that (phones_visible: own branch only)
                'seesPhones': bool(profile.can_see_customer_phone),
                'seesRecordPhones': access.record_phones_visible(user),
            }

        reference = {k: self._reference(seeded[f'branch{k}']['id']) for k in ('A', 'B')}
        out = Path(opts['out'])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({'branchA': seeded['branchA'], 'branchB': seeded['branchB'],
                                   'users': users, 'reference': reference},
                                  ensure_ascii=False, indent=1, default=str), encoding='utf-8')

        drift_rows = self._drift()
        self._write_drift(Path(opts['drift']), drift_rows)
        self.stdout.write(self.style.SUCCESS(
            f'[OK] expectations for {len(users)} users; drift rows: {len(drift_rows)}'))

    # ── reference records of one branch ───────────────────────────────────────
    @staticmethod
    def _reference(branch_id):
        from apps.customers.models import Customer, PurchaseHistory
        from apps.demand.models import DemandRecord
        from apps.pos_orders.models import SoftechSalesOrder
        from apps.reservations.models import Reservation
        from apps.shortage.models import ShortageList
        from apps.transfers.models import TransferRequest

        customers = (Customer.objects.filter(preferred_branch_id=branch_id)
                     .exclude(phone='').exclude(phone__isnull=True)
                     .order_by('-pk')[:SAMPLE['customers']])
        return {
            'customers': [{'id': c.pk, 'pic': c.softech_pic, 'phone': c.phone, 'name': c.name} for c in customers],
            'reservations': list(Reservation.objects.filter(branch_id=branch_id)
                                 .order_by('-pk').values_list('pk', flat=True)[:SAMPLE['reservations']]),
            'transfers': [{'id': pk, 'number': n} for pk, n in TransferRequest.objects
                          .filter(requesting_branch_id=branch_id).exclude(supplying_branch_id=branch_id)
                          .order_by('-pk').values_list('pk', 'request_number')[:SAMPLE['transfers']]],
            'demand': [{'id': pk, 'number': n} for pk, n in DemandRecord.objects.filter(branch_id=branch_id)
                       .order_by('-pk').values_list('pk', 'demand_number')[:SAMPLE['demand']]],
            'posOrders': list(SoftechSalesOrder.objects.filter(branch_id=branch_id)
                              .order_by('-pk').values_list('pk', flat=True)[:SAMPLE['posOrders']]),
            'shortage': list(ShortageList.objects.filter(branch_id=branch_id)
                             .order_by('-pk').values_list('pk', flat=True)[:SAMPLE['shortage']]),
            'invoices': list(PurchaseHistory.objects.filter(branch_id=branch_id)
                             .order_by('-invoice_date').values_list('softech_invoice_id', flat=True)[:SAMPLE['invoices']]),
        }

    # ── live matrix vs code ───────────────────────────────────────────────────
    @staticmethod
    def _drift():
        from apps.users.management.commands.seed_permissions import PERMISSIONS
        from apps.users.models import ACTION_CHOICES, RoleModuleAccess

        actions = [a for a, _ in ACTION_CHOICES]
        live = {(r, m, a): ok for r, m, a, ok in
                RoleModuleAccess.objects.values_list('role', 'module', 'action', 'is_allowed')}
        rows = []
        for role, modules in PERMISSIONS.items():
            if role == 'admin':
                continue
            for module, allowed in modules.items():
                for action in actions:
                    code = action in allowed
                    got = live.get((role, module, action))
                    if got is None and not code:
                        continue   # absent row = denied = same as code
                    if bool(got) != code:
                        rows.append((role, module, action, code, got))
        for (role, module, action), ok in live.items():
            if ok and module not in PERMISSIONS.get(role, {}) and role != 'admin':
                rows.append((role, module, action, False, True))
        return sorted(rows)

    @staticmethod
    def _write_drift(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ['# Permission drift: live role matrix vs code (seed_permissions)', '',
                 'Generated by `export_uat_expectations` on the UAT copy. "live" is what go-live has;',
                 '"code" is `seed_permissions.PERMISSIONS`. Each row is a finding for the owner.', '']
        if not rows:
            lines.append('No drift: every live row matches the code.')
        else:
            lines += ['| role | module | action | code | live |', '|---|---|---|---|---|']
            lines += [f'| {r} | {m} | {a} | {"allow" if c else "deny"} | '
                      f'{"missing" if g is None else ("allow" if g else "deny")} |' for r, m, a, c, g in rows]
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
