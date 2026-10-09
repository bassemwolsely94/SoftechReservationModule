"""B7 Option B — remove customers from the points system AT HQ: points flag off, special discount on, and
the balance earned since their reset cleared. Dry run unless --commit AND POINTS_REMOVAL_WRITE_ENABLED=True.

    python manage.py remove_from_points --user <username> [--limit 50] [--commit]          # reset customers (user 19)
    python manage.py remove_from_points --user <username> --pic 05HD999 [--commit]          # one code
    python manage.py remove_from_points --user <username> --reset-by 19 --reset-by 54      # other resetters
    python manage.py remove_from_points --user <username> --batches 60 --quiet --commit      # all, 50 per batch
Then the branch copies: push_customer_branch_copy --from-removals --branch N --batches 60 --quiet --commit.
"""
import csv
import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'B7 Option B — points flag off + balance cleared at HQ (dry run by default; 50 per run).'

    def add_arguments(self, parser):
        parser.add_argument('--user', required=True)
        parser.add_argument('--pic', action='append', default=[])
        parser.add_argument('--reset-by', action='append', default=[], help='SOFTECH user of the reset (default 19)')
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--batches', type=int, default=1, help='repeat up to N batches (stops at a problem)')
        parser.add_argument('--quiet', action='store_true', help='only the summary line per batch')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *a, **o):
        from apps.customers import points_removal as PR
        from apps.users.models import StaffProfile
        user = (StaffProfile.objects.select_related('user').filter(user__username__iexact=o['user']).first()
                or StaffProfile.objects.select_related('user').filter(softech_user_id=o['user']).first())
        if user is None or not (user.is_active and user.user.is_active) or user.role not in ('admin', 'supervisor'):
            raise CommandError('--user must be an active admin or supervisor (your login name in our system)')
        batches = max(1, o['batches']) if not o['pic'] else 1
        for n in range(1, batches + 1):
            recs = PR.run(pics=o['pic'] or None, user=user, commit=o['commit'], limit=o['limit'] or None,
                          users=tuple(o['reset_by'] or ['19']))
            problem = self._report(recs, o, n if batches > 1 else 0)
            if not recs or problem or not o['commit']:
                break
        if not o['commit']:
            self.stdout.write(self.style.WARNING('dry run — add --commit (and POINTS_REMOVAL_WRITE_ENABLED=True) to write'))

    def _report(self, recs, o, batch_no):
        counts, cleared, planned = {}, 0, 0
        for r in recs:
            counts[r.status] = counts.get(r.status, 0) + 1
            if r.status == 'verified':
                cleared += r.points_cleared
            elif r.status == 'dry_run':
                planned += r.points_cleared
            if o['quiet'] and r.status not in ('conflict', 'failed'):
                continue
            self.stdout.write(f'{r.pic}: {r.status} · flag {r.flag_before}→{r.flag_after if r.flag_after is not None else "-"}'
                              f' · balance {r.balance_before}→{r.balance_after if r.balance_after is not None else "-"}'
                              f' · discount {r.discount_before}→{r.discount_after if r.discount_after is not None else "-"}'
                              + (f' — {r.error}' if r.error else ''))
        self.stdout.write((f'batch {batch_no}: ' if batch_no else '') + f'{len(recs)} codes - ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items()))
                          + f' - points cleared: {cleared}' + (f' - points to clear (dry run): {planned}' if planned else ''))
        if recs:
            os.makedirs('scratch', exist_ok=True)
            path = os.path.join('scratch', f'points_removal_{timezone.localtime():%Y%m%d_%H%M%S_%f}.csv')
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['pic', 'status', 'flag_before', 'balance_before', 'discount_before', 'flag_after',
                            'balance_after', 'discount_after', 'points_cleared', 'error'])
                for r in recs:
                    w.writerow([r.pic, r.status, r.flag_before, r.balance_before, r.discount_before, r.flag_after,
                                r.balance_after, r.discount_after, r.points_cleared, r.error])
            self.stdout.write(f'review list: {path}')
        return bool(counts.get('conflict') or counts.get('failed'))
