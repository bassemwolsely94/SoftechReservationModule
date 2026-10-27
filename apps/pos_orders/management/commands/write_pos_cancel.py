"""
write_pos_cancel — batch-write OUR POS item-selection telemetry into SOFTECH pos_cancel
(the «المبيعات غير المخزنة» activity log). Gated by settings.POS_CANCEL_WRITE_ENABLED.

Usage:
  python manage.py write_pos_cancel                 # dry-run unless the flag is ON
  python manage.py write_pos_cancel --dry-run       # force dry-run (show what WOULD write)
  python manage.py write_pos_cancel --live          # force live write (requires flag ON)
  python manage.py write_pos_cancel --min-age 0     # ignore the finalize-grace window (testing)
  python manage.py write_pos_cancel --limit 500
"""
import json
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Batch-write POS selection telemetry into SOFTECH pos_cancel (gated, idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Force dry-run (no writes).')
        parser.add_argument('--live', action='store_true', help='Force live write (needs flag ON).')
        parser.add_argument('--limit', type=int, default=2000)
        parser.add_argument('--min-age', type=int, default=360,
                            help='Only events older than N minutes (let carts finalize). Default 360.')

    def handle(self, *args, **opts):
        from apps.pos_orders.pos_cancel_writer import write_pos_cancel_batch, write_enabled
        dry_run = True if opts['dry_run'] else (False if opts['live'] else None)
        if opts['live'] and not write_enabled():
            self.stderr.write(self.style.ERROR(
                'POS_CANCEL_WRITE_ENABLED is False — refusing --live. Set the flag first.'))
            return
        s = write_pos_cancel_batch(dry_run=dry_run, limit=opts['limit'], min_age_minutes=opts['min_age'])
        mode = 'DRY-RUN' if s['dry_run'] else 'LIVE'
        self.stdout.write(self.style.SUCCESS(
            f"[{mode}] candidates={s['candidates']} written={s['written']} "
            f"skipped_sold={s['skipped_sold']} (flag={'ON' if s['write_enabled'] else 'OFF'})"))
        for bc, d in sorted(s['branches'].items()):
            if s['dry_run']:
                self.stdout.write(f"  branch {bc}: would_write={d.get('would_write')}")
                for row in d.get('sample', []):
                    self.stdout.write('     ' + json.dumps(row, ensure_ascii=False, default=str))
            elif 'error' in d:
                self.stdout.write(self.style.WARNING(f"  branch {bc}: ERROR {d['error']}"))
            else:
                self.stdout.write(f"  branch {bc}: written={d.get('written')}")
