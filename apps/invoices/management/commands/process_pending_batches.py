"""
Durability worker for multi-invoice bundle ingestion.

Bundle processing normally runs on a daemon thread kicked off at upload time. If
the web process restarts mid-run, a batch can be left stuck in 'processing' with
no thread to finish it. This command re-processes such batches (and any left in
'pending'), so nothing is silently lost. Run it from the scheduler every few
minutes, or by hand:

    python manage.py process_pending_batches
    python manage.py process_pending_batches --stale-minutes 10
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.invoices.models import InvoiceBatch
from apps.invoices import ingest


class Command(BaseCommand):
    help = 'Re-process invoice bundles stuck in pending/processing (durability).'

    def add_arguments(self, parser):
        parser.add_argument('--stale-minutes', type=int, default=10,
                            help="Only re-run 'processing' batches older than this (default 10).")
        parser.add_argument('--limit', type=int, default=20)

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(minutes=opts['stale_minutes'])
        qs = (InvoiceBatch.objects
              .filter(models_q(cutoff))
              .order_by('created_at')[:opts['limit']])
        n = 0
        for batch in qs:
            self.stdout.write(f'reprocessing batch {batch.id} (status={batch.status})')
            # clear any partial children not yet queued/posted, then rerun
            batch.invoices.exclude(status__in=['queued', 'pushing', 'finalized']).delete()
            ingest.process_bundle(batch.pk)
            n += 1
        self.stdout.write(self.style.SUCCESS(f'processed {n} batch(es)'))


def models_q(cutoff):
    from django.db.models import Q
    return Q(status='pending') | Q(status='processing', updated_at__lt=cutoff)
