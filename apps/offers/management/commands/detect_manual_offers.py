"""
detect_manual_offers — scan the sales mirror for historical MANUAL promos and
record ManualOfferMatch provenance rows. READ-ONLY vs SOFTECH (writes only the PG
detection table). Idempotent (update-in-place per line).

    python manage.py detect_manual_offers --months 3
    python manage.py detect_manual_offers --branch 5 --limit 5000
    python manage.py detect_manual_offers --dry            # classify + report, persist nothing
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.offers.detection import detect_manual_offers


class Command(BaseCommand):
    help = 'Detect historical manual promo transactions in the sales mirror.'

    def add_arguments(self, parser):
        parser.add_argument('--months', type=int, default=0, help='Look back N months (0 = all history).')
        parser.add_argument('--branch', type=int, default=None, help='Restrict to a branch id.')
        parser.add_argument('--limit', type=int, default=None, help='Cap lines scanned (debug).')
        parser.add_argument('--dry', action='store_true', help='Classify + report only; write nothing.')

    def handle(self, *args, **o):
        since = None
        if o['months']:
            since = timezone.now() - timedelta(days=30 * o['months'])
        counts = detect_manual_offers(since=since, branch_id=o['branch'],
                                      limit=o['limit'], persist=not o['dry'])
        mode = 'DRY (nothing written)' if o['dry'] else 'persisted'
        self.stdout.write(self.style.SUCCESS(
            f"Manual-offer detection [{mode}] — scanned {counts['scanned']}: "
            f"exact={counts['exact_offer']}, bxgy={counts['bxgy_cheapest']}, "
            f"unmapped={counts['unmapped_discount']}"
        ))
