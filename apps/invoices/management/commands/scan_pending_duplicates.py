"""
Scan review-stage supplier invoices for SOFTECH duplicates and cache the result,
so the invoice list flags re-entries before anyone opens them.

Runs the thorough multi-factor check (writer.check_duplicates) and stores a compact
summary on each invoice (dup_check + dup_checked_at). Safe to run repeatedly / on a
schedule; read-only against SOFTECH.

    python manage.py scan_pending_duplicates [--status review] [--limit 200] [--all] [--stale-hours 12]
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.invoices.models import SupplierInvoice
from apps.invoices import writer


class Command(BaseCommand):
    help = 'Cache thorough SOFTECH duplicate-check results for review-stage invoices.'

    def add_arguments(self, parser):
        parser.add_argument('--status', default='review',
                            help="Invoice status to scan (default 'review'). Use --all to ignore.")
        parser.add_argument('--all', action='store_true', help='Scan every non-finalized invoice.')
        parser.add_argument('--limit', type=int, default=200)
        parser.add_argument('--stale-hours', type=int, default=12,
                            help='Re-scan invoices whose cache is older than this (0 = always).')

    def handle(self, *args, **o):
        qs = SupplierInvoice.objects.all()
        if not o['all']:
            qs = qs.filter(status=o['status'])
        else:
            qs = qs.exclude(status='finalized')
        # skip freshly-scanned ones unless stale
        if o['stale_hours']:
            cutoff = timezone.now() - timedelta(hours=o['stale_hours'])
            qs = qs.filter(dup_checked_at__isnull=True) | qs.filter(dup_checked_at__lt=cutoff)
        qs = qs.distinct().order_by('-created_at')[:o['limit']]

        n = flagged = 0
        for inv in qs:
            s = writer.scan_invoice_duplicates(inv)
            n += 1
            if s.get('is_duplicate') or s.get('likely_duplicate'):
                flagged += 1
                self.stdout.write(f"  ⚠ inv#{inv.id} {inv.supplier_name or ''} — "
                                  f"{'DUPLICATE' if s.get('is_duplicate') else 'likely'} "
                                  f"(score {s.get('best_score')}, doc {s.get('softech_docnumber')})")
        self.stdout.write(self.style.SUCCESS(f'scanned {n} invoice(s); {flagged} flagged as (likely) duplicates.'))
