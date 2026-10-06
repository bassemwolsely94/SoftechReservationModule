"""
apps/audit/management/commands/run_abuse_detection.py

Usage:
    python manage.py run_abuse_detection
    python manage.py run_abuse_detection --hours 48
    python manage.py run_abuse_detection --erp-only
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run anti-abuse detection scan and flag suspicious activity'

    def add_arguments(self, parser):
        parser.add_argument('--hours',    type=int, default=24, help='Window in hours (default 24)')
        parser.add_argument('--erp-only', action='store_true',  help='Only check ERP mismatches')
        parser.add_argument('--days',     type=int, default=7,  help='Days back for ERP mismatch check')

    def handle(self, *args, **options):
        from apps.audit.detector import run_abuse_detection, detect_erp_mismatches

        hours    = options['hours']
        erp_only = options['erp_only']

        if not erp_only:
            self.stdout.write(f'→ Running pattern detection (last {hours}h)...')
            flags = run_abuse_detection(window_hours=hours)
            self.stdout.write(
                self.style.SUCCESS(f'  ✓ {flags} abuse flags created')
                if flags else f'  ✓ No patterns detected'
            )

        self.stdout.write(f'→ Checking ERP mismatches (last {options["days"]} days)...')
        mismatches = detect_erp_mismatches(days=options['days'])
        self.stdout.write(
            self.style.WARNING(f'  ⚠ {mismatches} unvalidated fulfilled reservations flagged')
            if mismatches else f'  ✓ No ERP mismatches'
        )
