"""Merge APPROVED duplicate customer codes into their main code at HQ (B7 merge part 2, apps/customers/merge_write.py).
Dry run unless --commit AND CUSTOMER_MERGE_WRITE_ENABLED=True.

Pilot one pair (old code; it must be approved in /customers/merge first):
    python manage.py merge_customer_codes --pic 03HD3059 --user <username> [--commit]
Approved pairs in approval order (≤ CUSTOMER_MERGE_BATCH_MAX per batch; stops at the first problem):
    python manage.py merge_customer_codes --approved --user <username> --batches 10 --quiet --commit
Then the branch copies: check_customer_status_drift → push_customer_branch_copy --from-drift --branch <code>.
Every batch writes a review list to scratch/ (codes only).
"""
import csv
import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'B7 — merge approved duplicate customer codes at HQ (points moved, old code closed; dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--pic', action='append', default=[], help='old code of an approved (or failed) pair')
        parser.add_argument('--approved', action='store_true', help='batch: approved pairs, oldest approval first')
        parser.add_argument('--user', required=True, help='our username / SOFTECH user id of the person running it')
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--batches', type=int, default=1)
        parser.add_argument('--quiet', action='store_true')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *a, **o):
        from apps.customers import merge_write as MW
        from apps.users.models import StaffProfile
        user = (StaffProfile.objects.select_related('user').filter(user__username__iexact=o['user']).first()
                or StaffProfile.objects.select_related('user').filter(softech_user_id=o['user']).first())
        if user is None:
            raise CommandError(f"no staff profile for username / SOFTECH user id {o['user']!r}")
        if not (user.is_active and user.user.is_active) or user.role not in ('admin', 'supervisor'):
            raise CommandError(f'{user.user.username}: must be an active admin or supervisor')
        if bool(o['pic']) == o['approved']:
            raise CommandError('give exactly one of --pic, --approved')
        batches = 1 if o['pic'] else max(1, o['batches'])
        for n in range(1, batches + 1):
            try:
                recs = MW.run(pics=o['pic'] or None, user=user, commit=o['commit'], limit=o['limit'] or None)
            except ValueError as exc:
                raise CommandError(str(exc))
            if not recs:
                self.stdout.write('nothing to merge' + ('' if o['pic'] else ' (no approved pairs)'))
                break
            problem = self._report(recs, o, n if batches > 1 else 0)
            if problem or not o['commit']:
                break
        if not o['commit']:
            self.stdout.write(self.style.WARNING('dry run — add --commit (and CUSTOMER_MERGE_WRITE_ENABLED=True) to write'))
        else:
            self.stdout.write('branch copies: check_customer_status_drift, then push_customer_branch_copy --from-drift')

    def _report(self, recs, o, batch_no):
        for r in recs:
            if o['quiet'] and r.status not in ('conflict', 'failed'):
                continue
            b = r.before or {}
            ob, mb = b.get('old') or {}, b.get('main') or {}
            self.stdout.write(f'{r.old_pic} -> {r.main_pic}: {r.status}' + (f' - {r.error}' if r.error else ''))
            if ob:
                self.stdout.write(f"    old  status {ob.get('status')!r} balance {ob.get('balance')} points "
                                  f"{int(bool(ob.get('points')))} | main status {mb.get('status')!r} "
                                  f"balance {mb.get('balance')} points {int(bool(mb.get('points')))} | "
                                  f'points to move {r.points_moved}')
            a = r.after or {}
            if a and r.status != 'no_change':
                oa, ma = a.get('old') or {}, a.get('main') or {}
                self.stdout.write(f"    read back: old status {oa.get('status')!r} balance {oa.get('balance')} | "
                                  f"main balance {ma.get('balance')} | debit {a.get('debit')} credit {a.get('credit')}")
        counts = {}
        for r in recs:
            counts[r.status] = counts.get(r.status, 0) + 1
        moved = sum(r.points_moved for r in recs if r.status == 'verified')
        self.stdout.write((f'batch {batch_no}: ' if batch_no else '') + f'{len(recs)} pairs - '
                          + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())) + f' - points moved {moved}')
        path = os.path.join('scratch', f'merge_codes_{timezone.localtime():%Y%m%d_%H%M%S_%f}.csv')
        os.makedirs('scratch', exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['old_pic', 'main_pic', 'status', 'points_moved', 'error'])
            for r in recs:
                w.writerow([r.old_pic, r.main_pic, r.status, r.points_moved, r.error])
        self.stdout.write(f'review list: {path}')
        return bool(counts.get('conflict') or counts.get('failed'))
