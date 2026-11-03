"""
python manage.py sync_pbx_cdr                      # incremental (newest stored call − 3 h → now)
python manage.py sync_pbx_cdr --since 2024-08-01   # backfill (read-only, weekly chunks)
python manage.py sync_pbx_cdr --relink-only        # re-resolve every stored call's PIC

Read-only copy of Issabel's CDR into pbx.CdrCall, linked to PICs (apps/pbx/cdr.py).
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Mirror the Issabel CDR (customer calls) into pbx.CdrCall and link each call to a PIC'

    def add_arguments(self, parser):
        parser.add_argument('--since', help='YYYY-MM-DD (default: incremental)')
        parser.add_argument('--until', help='YYYY-MM-DD (default: now)')
        parser.add_argument('--chunk-days', type=int, default=7)
        parser.add_argument('--relink-only', action='store_true')

    def handle(self, *args, **opts):
        from config.issabel import cdr_configured
        from apps.pbx import cdr

        if opts['relink_only']:
            cdr.relink_all(log=self.stdout.write)
            return
        if not cdr_configured():
            raise CommandError('ISSABEL_CDR_USER / ISSABEL_CDR_PASSWORD are not set in .env')

        def day(v):
            return datetime.strptime(v, '%Y-%m-%d') if v else None
        run = cdr.sync_cdr(since=day(opts['since']), until=day(opts['until']),
                           chunk_days=opts['chunk_days'], log=self.stdout.write)
        msg = f'{run.status}: {run.fetched} CDR rows read, {run.stored} customer calls stored'
        if run.status != 'success':
            raise CommandError(f'{msg} — {run.error}')
        self.stdout.write(self.style.SUCCESS(msg))
