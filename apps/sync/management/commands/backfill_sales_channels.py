"""
apps/sync/management/commands/backfill_sales_channels.py

Backfill PurchaseHistory.sales_channel, sales_person_type, and softech_phcode
for ALL existing invoices using the AUTHORITATIVE source on stktransm:
  • ptclassifcode / ptcode   — sales channel and person type
  • phcode                   — customer PIC stamped on this invoice

This fixes historic incorrect values and also populates the new softech_phcode
field so distinct-PIC counts are accurate (31 → ~278 for 18/05/2026).

Usage:
    python manage.py backfill_sales_channels              # last 90 days
    python manage.py backfill_sales_channels --days 365
    python manage.py backfill_sales_channels --dry-run

ABSOLUTE RULE: SELECT only on Sybase. Never INSERT/UPDATE/DELETE.
"""
import datetime as _dt
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

logger = logging.getLogger('elrezeiky.sync')

# Fetch stktransm in monthly chunks to avoid killing the connection
# with a single huge result set.  Also pulls phcode to populate softech_phcode.
_QUERY_CHANNEL_CHUNK = """
    SELECT sm.branchcode, sm.doccode, sm.docnumber, sm.docdate,
           sm.ptcode, sm.ptclassifcode, sm.phcode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.doccode IN ('115', '30')
      AND sm.docdate >= '{date_from}'
      AND sm.docdate <  '{date_to}'
"""


def _norm_docnum(v):
    if v is None:
        return 'nonum'
    try:
        return str(int(float(str(v))))
    except (ValueError, OverflowError):
        return str(v).strip()


class Command(BaseCommand):
    help = (
        'Backfill PurchaseHistory.sales_channel, sales_person_type, and '
        'softech_phcode from stktransm.ptclassifcode / ptcode / phcode '
        '(authoritative per-invoice values). Fixes distinct-PIC counts.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=90,
            help='Days of history to backfill (default: 90)',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without writing anything',
        )

    def handle(self, *args, **options):
        days    = options['days']
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY-RUN — no writes'))

        from apps.customers.models import PurchaseHistory

        # ── Step 1: Pull channel data from Sybase in monthly chunks ──────────
        self.stdout.write(f'Connecting to Sybase and loading channel data ({days} days) …')
        try:
            from config.sybase import get_sybase_connection
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Cannot import sybase connector: {exc}'))
            return

        # Build list of (date_from, date_to) monthly windows
        today = _dt.date.today()
        start = today - _dt.timedelta(days=days)
        windows = []
        d = start
        while d < today:
            next_d = _dt.date(d.year + (d.month // 12), (d.month % 12) + 1, 1) \
                     if d.month < 12 else _dt.date(d.year + 1, 1, 1)
            next_d = min(next_d, today + _dt.timedelta(days=1))
            windows.append((d.strftime('%Y-%m-%d'), next_d.strftime('%Y-%m-%d')))
            d = next_d

        # inv_id → (ptclassifcode, ptcode, phcode)
        inv_map: dict[str, tuple[str, str, str]] = {}
        total_sybase_rows = 0

        for date_from, date_to in windows:
            try:
                conn = get_sybase_connection()
                cur  = conn.cursor()
                sql  = _QUERY_CHANNEL_CHUNK.format(date_from=date_from, date_to=date_to)
                cur.execute(sql)
                rows = cur.fetchall()
                conn.close()
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f'  [{date_from}→{date_to}] Sybase error: {exc}')
                )
                continue

            for row in rows:
                branchcode    = str(row[0] or '').strip()
                doccode       = str(row[1] or '').strip()
                docnumber     = _norm_docnum(row[2])
                docdate       = row[3]
                ptcode        = str(row[4] or '').strip()
                ptclassifcode = str(row[5] or '').strip()
                phcode        = str(row[6] or '').strip() if len(row) > 6 else ''

                if isinstance(docdate, _dt.datetime):
                    date_str = docdate.strftime('%Y%m%d')
                else:
                    date_str = str(docdate)[:10].replace('-', '') if docdate else 'nodate'

                inv_id = f"{branchcode}-{doccode}-{docnumber}-{date_str}"
                inv_map[inv_id] = (ptclassifcode, ptcode, phcode)

            total_sybase_rows += len(rows)
            self.stdout.write(
                f'  [{date_from} → {date_to}] {len(rows):,} rows '
                f'({total_sybase_rows:,} total)'
            )

        if not inv_map:
            self.stdout.write(self.style.WARNING('No invoice data loaded from Sybase.'))
            return

        # Channel distribution preview
        from collections import Counter
        ch_dist = Counter(ch for ch, _pt, _ph in inv_map.values() if ch)
        self.stdout.write(f'\nChannel distribution in stktransm ({len(inv_map):,} invoices):')
        for code, n in ch_dist.most_common():
            self.stdout.write(f'  ptclassifcode={code!r}: {n:,} invoices')

        # ── Step 2: Bulk-update PurchaseHistory in PostgreSQL ─────────────────
        self.stdout.write('\nApplying updates to PurchaseHistory …')

        CHUNK = 10_000
        inv_ids_all   = list(inv_map.keys())
        total_updated = 0
        total_no_change = 0
        total_not_found = 0

        for chunk_start in range(0, len(inv_ids_all), CHUNK):
            chunk_ids = inv_ids_all[chunk_start : chunk_start + CHUNK]

            qs = PurchaseHistory.objects.filter(
                softech_invoice_id__in=chunk_ids
            ).only('id', 'softech_invoice_id', 'sales_channel', 'sales_person_type',
                   'softech_phcode')

            to_update = []
            found_ids = set()
            for ph in qs:
                found_ids.add(ph.softech_invoice_id)
                ch, pt, phcode = inv_map.get(ph.softech_invoice_id, ('', '', ''))
                if (ph.sales_channel != ch
                        or ph.sales_person_type != pt
                        or ph.softech_phcode != phcode):
                    ph.sales_channel     = ch
                    ph.sales_person_type = pt
                    ph.softech_phcode    = phcode
                    to_update.append(ph)
                else:
                    total_no_change += 1

            total_not_found += len(set(chunk_ids) - found_ids)

            if to_update and not dry_run:
                with transaction.atomic():
                    PurchaseHistory.objects.bulk_update(
                        to_update,
                        ['sales_channel', 'sales_person_type', 'softech_phcode'],
                        batch_size=2000,
                    )

            total_updated += len(to_update)
            self.stdout.write(
                f'  chunk {chunk_start // CHUNK + 1}: '
                f'{len(to_update)} updated | {total_no_change} already-correct | '
                f'{total_not_found} not in PG'
            )

        # ── Step 3: Invalidate analytics cache ────────────────────────────────
        if not dry_run and total_updated:
            try:
                import apps.analytics.views as _av
                _av._channel_label_cache     = None
                _av._person_type_label_cache = None
            except Exception:
                pass

        # ── Final report ──────────────────────────────────────────────────────
        verb = 'Would update' if dry_run else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f'\n{verb} {total_updated:,} PurchaseHistory records.\n'
            f'  Already correct : {total_no_change:,}\n'
            f'  Not in PG yet   : {total_not_found:,} (run --full sync to add them)\n'
            f'  Sybase rows read: {total_sybase_rows:,}'
        ))
