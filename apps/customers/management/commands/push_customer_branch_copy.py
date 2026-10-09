"""Copy customers' HQ account flags (status / lock / deceased / points / special discount) onto a branch
node's own copy (B7 step 3). Dry run unless --commit AND CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True.

One code (all differing flags):
    python manage.py push_customer_branch_copy --pic 05HD999 --branch 140 --user <username> [--commit]
Batch from the daily status check (only flags that make the branch STRICTER; special discount only with
--include-discount; codes whose copy would relax the branch are skipped; stops at the first conflict):
    python manage.py push_customer_branch_copy --from-drift --branch 140 --user <username> [--limit 50] [--commit]
Every run writes a review list to scratch/ (codes only).
"""
import csv
import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'B7 step 3 — copy HQ customer flags onto a branch copy (audited, read back; dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--pic', action='append', default=[])
        parser.add_argument('--from-drift', action='store_true',
                            help='batch: codes with an open HQ-stricter difference on --branch')
        parser.add_argument('--branch', required=True)
        parser.add_argument('--user', required=True, help='our username of the person running it (audit)')
        parser.add_argument('--limit', type=int, default=0, help='batch size (≤ CUSTOMER_BRANCH_COPY_BATCH_MAX)')
        parser.add_argument('--include-discount', action='store_true',
                            help='batch: also copy special discount (picdiscounts) — a pricing change')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *a, **o):
        from apps.customers import branch_copy as BC
        from apps.users.models import StaffProfile
        user = (StaffProfile.objects.select_related('user').filter(user__username__iexact=o['user']).first()
                or StaffProfile.objects.select_related('user').filter(softech_user_id=o['user']).first())
        if user is None:
            raise CommandError(f"no staff profile for username / SOFTECH user id {o['user']!r} — "
                               'use your login name in our system')
        if not (user.is_active and user.user.is_active) or user.role not in ('admin', 'supervisor'):
            raise CommandError(f"{user.user.username}: role={user.role!r} active={user.is_active and user.user.is_active}"
                               ' — must be an active admin or supervisor')
        if bool(o['pic']) == bool(o['from_drift']):
            raise CommandError('give either --pic (one code) or --from-drift (batch)')
        try:
            if o['from_drift']:
                recs = BC.run_batch(o['branch'], user=user, commit=o['commit'], limit=o['limit'] or None,
                                    include_discount=o['include_discount'])
            else:
                recs = BC.run(o['pic'], o['branch'], user=user, commit=o['commit'])
        except ValueError as exc:
            raise CommandError(str(exc))

        for r in recs:
            self.stdout.write(f'{r.pic} @ branch {r.node_branch}: {r.status}' + (f' — {r.error}' if r.error else ''))
            if not o['from_drift'] or len(recs) <= 5:
                for c in BC.FLAGS:
                    b, t, af = r.before.get(c), r.target.get(c), r.after.get(c, '')
                    mark = '  ← change' if b != t else ''
                    self.stdout.write(f'    {c:13} branch {b!s:>4} → HQ {t!s:>4}'
                                      + (f'   read back {af}' if r.after else '') + mark)
        counts = {}
        for r in recs:
            counts[r.status] = counts.get(r.status, 0) + 1
        self.stdout.write(f'{len(recs)} codes · ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
        path = self._write_list(recs, o, BC)
        if path:
            self.stdout.write(f'review list: {path}')
        if not o['commit']:
            self.stdout.write(self.style.WARNING('dry run — add --commit (and CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True) to write'))

    def _write_list(self, recs, o, BC):
        if not recs:
            return ''
        path = os.path.join('scratch', f"branch_copy_{o['branch']}_{timezone.localtime():%Y%m%d_%H%M%S}.csv")
        os.makedirs('scratch', exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['pic', 'branch', 'status', 'error'] + [f'{c}_branch' for c in BC.FLAGS]
                       + [f'{c}_hq' for c in BC.FLAGS] + [f'{c}_read_back' for c in BC.FLAGS])
            for r in recs:
                w.writerow([r.pic, r.node_branch, r.status, r.error]
                           + [r.before.get(c, '') for c in BC.FLAGS] + [r.target.get(c, '') for c in BC.FLAGS]
                           + [r.after.get(c, '') for c in BC.FLAGS])
        return path
