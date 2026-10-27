"""
Backfill SOFTECH itemssuppliers.suppitemcode from everything we've already
confirmed — so the invoice-ingest tier-0 recall (code → item) starts hitting
without waiting for each mapping to be re-confirmed one invoice at a time.

Sources (deduped to (personcode, itemcode, suppitemcode) triples):
  • VendorItemMapping rows that carry a vendor_item_code
  • confirmed InvoiceLine rows (item + vendor_item_code) whose invoice has a vendor

Every write goes through the hardened, collision-safe writer.inject_mapping:
  no-clobber (won't overwrite a different code), collision-refuse (a code already
  on another item is skipped), noop when already set.

    python manage.py seed_supplier_items                 # DRY-RUN (probe, no writes)
    python manage.py seed_supplier_items --commit        # persist
    python manage.py seed_supplier_items --source mappings --limit 500
"""
from collections import Counter

from django.core.management.base import BaseCommand

from apps.invoices import supplier_items
from apps.invoices.models import VendorItemMapping, InvoiceLine


class Command(BaseCommand):
    help = 'Seed SOFTECH itemssuppliers.suppitemcode from confirmed vendor-code mappings.'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true',
                            help='Persist the writes (default: dry-run probe, rolls back).')
        parser.add_argument('--source', choices=['mappings', 'lines', 'both'], default='both')
        parser.add_argument('--limit', type=int, default=0, help='Cap the number of triples.')

    def _triples(self, source):
        """Yield unique (personcode, itemcode, suppitemcode) from the chosen sources."""
        seen = set()
        if source in ('mappings', 'both'):
            qs = (VendorItemMapping.objects
                  .exclude(vendor_item_code='')
                  .select_related('vendor', 'item'))
            for m in qs.iterator():
                pc = (m.vendor.softech_personcode or '').strip() if m.vendor_id else ''
                ic = (m.item.softech_id or '').strip() if m.item_id else ''
                code = (m.vendor_item_code or '').strip()
                key = (pc, ic, code)
                if pc and ic and code and key not in seen:
                    seen.add(key)
                    yield key
        if source in ('lines', 'both'):
            qs = (InvoiceLine.objects
                  .filter(is_confirmed=True, item__isnull=False)
                  .exclude(vendor_item_code='')
                  .select_related('item', 'invoice__vendor'))
            for l in qs.iterator():
                inv = l.invoice
                pc = (inv.vendor.softech_personcode or '').strip() if inv and inv.vendor_id else ''
                ic = (l.item.softech_id or '').strip() if l.item_id else ''
                code = (l.vendor_item_code or '').strip()
                key = (pc, ic, code)
                if pc and ic and code and key not in seen:
                    seen.add(key)
                    yield key

    def handle(self, *args, **opts):
        commit = opts['commit']
        triples = list(self._triples(opts['source']))
        if opts['limit']:
            triples = triples[:opts['limit']]
        self.stdout.write(f'{len(triples)} unique (vendor, item, code) triples from '
                          f'source={opts["source"]}. Mode={"COMMIT" if commit else "DRY-RUN"}.')
        if not triples:
            return

        conn = supplier_items.open_conn()
        tally = Counter()
        conflicts = []
        try:
            for pc, ic, code in triples:
                try:
                    r = supplier_items.inject_mapping(conn, pc, ic, code, commit=commit)
                except Exception as e:
                    tally['error'] += 1
                    self.stderr.write(f'  ERROR {pc}/{ic}/{code}: {e}')
                    continue
                action = r.get('action', '?') if r.get('ok') else (r.get('action') or r.get('reason') or 'fail')
                tally[action] += 1
                # A bulk seed never auto-applies a CHANGE to an existing mapping —
                # those surface for a human to approve individually in the UI.
                if action == 'needs_approval':
                    conflicts.append((pc, ic, code, r))
        finally:
            conn.close()

        self.stdout.write(self.style.SUCCESS('\n=== summary ==='))
        for k, v in sorted(tally.items(), key=lambda x: -x[1]):
            self.stdout.write(f'  {k:26} {v}')
        if conflicts:
            self.stdout.write(self.style.WARNING(
                f'\n{len(conflicts)} mapping change(s) need manual approval (NOT applied):'))
            for pc, ic, code, r in conflicts[:15]:
                self.stdout.write(f'  vendor {pc} item {ic} code {code} → {r.get("discrepancies")}')
        if not commit:
            self.stdout.write(self.style.NOTICE('\nDRY-RUN — nothing written. Re-run with --commit to persist.'))
