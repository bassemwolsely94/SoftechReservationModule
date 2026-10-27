"""Rebuild the B7 duplicate-code merge queue from HQ (READ-ONLY vs SOFTECH; writes only our MergeCandidate rows).

    python manage.py build_merge_candidates
Review in the app: Customers → دمج الأكواد المكررة (/customers/merge). Runs weekly (Sat 05:30) by the scheduler.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'B7 — rebuild the duplicate customer-code merge queue (read-only vs SOFTECH).'

    def handle(self, *a, **o):
        from apps.customers import duplicates as DUP
        r = DUP.rebuild_locked()
        if r is None:
            raise CommandError('another rebuild is running')
        self.stdout.write(f"HQ codes {r['hq_codes']} - candidates {r['candidates']} "
                          f"(strong {r['by_strength']['strong']}, same name {r['by_strength']['medium']}, "
                          f"review {r['by_strength']['review']}) - new {r['new']}, updated {r['updated']}, "
                          f"decisions kept {r['kept']}, no longer duplicate {r['stale']}")
