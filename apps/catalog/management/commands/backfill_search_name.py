"""
backfill_search_name — (re)compute Item.search_name for the universal-search
overlay.

Run once after the migration to populate existing rows, and any time the
normalization logic changes. Idempotent; only writes rows whose haystack actually
changed. The item sync also refreshes search_name inline, so day-to-day this
command is not required.

    python manage.py backfill_search_name            # all items
    python manage.py backfill_search_name --limit 500 # smoke test
"""
from django.core.management.base import BaseCommand

from apps.catalog.models import Item
from apps.catalog.search_index import search_name_for


class Command(BaseCommand):
    help = 'Recompute Item.search_name (normalized universal-search haystack).'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0,
                            help='Only process the first N items (0 = all).')
        parser.add_argument('--batch', type=int, default=2000,
                            help='bulk_update batch size.')

    def handle(self, *args, **opts):
        qs = Item.objects.all().only(
            'id', 'softech_id', 'name', 'name_scientific', 'barcode', 'search_name',
        ).order_by('id')
        if opts['limit']:
            qs = qs[:opts['limit']]

        changed, scanned = [], 0
        for item in qs.iterator(chunk_size=2000):
            scanned += 1
            new = search_name_for(item)
            if new != item.search_name:
                item.search_name = new
                changed.append(item)
                if len(changed) >= opts['batch']:
                    Item.objects.bulk_update(changed, ['search_name'])
                    changed.clear()
        if changed:
            Item.objects.bulk_update(changed, ['search_name'])

        self.stdout.write(self.style.SUCCESS(
            f'search_name backfill complete — scanned {scanned}, updated rows written in batches.'
        ))
