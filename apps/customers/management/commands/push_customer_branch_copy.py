"""Copy customers' HQ account flags (status / lock / deceased / points / special discount) onto a branch
node's own copy (B7 step 3). Dry run unless --commit AND CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True.

    python manage.py push_customer_branch_copy --pic 05HD999 --branch 140 --user <username>            # dry run
    python manage.py push_customer_branch_copy --pic 05HD999 --branch 140 --user <username> --commit
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'B7 step 3 — copy HQ customer flags onto a branch copy (audited, read back; dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--pic', action='append', required=True)
        parser.add_argument('--branch', required=True)
        parser.add_argument('--user', required=True, help='our username of the person running it (audit)')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *a, **o):
        from apps.customers import branch_copy as BC
        from apps.users.models import StaffProfile
        user = StaffProfile.objects.filter(user__username=o['user']).first()
        if user is None or not user.is_active or user.role not in ('admin', 'supervisor'):
            raise CommandError('--user must be an active admin or supervisor')
        try:
            recs = BC.run(o['pic'], o['branch'], user=user, commit=o['commit'])
        except ValueError as exc:
            raise CommandError(str(exc))
        for r in recs:
            self.stdout.write(f'{r.pic} @ branch {r.node_branch}: {r.status}' + (f' — {r.error}' if r.error else ''))
            for c in BC.FLAGS:
                b, t, af = r.before.get(c), r.target.get(c), r.after.get(c, '')
                mark = '  ← change' if b != t else ''
                self.stdout.write(f'    {c:13} branch {b!s:>4} → HQ {t!s:>4}' + (f'   read back {af}' if r.after else '') + mark)
        if not o['commit']:
            self.stdout.write(self.style.WARNING('dry run — add --commit (and CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True) to write'))
