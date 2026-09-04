"""
sync_purchase_expiry
====================
Backfill / refresh the local mirror of doccode-10 purchase-invoice lines that
carry an entered expiry date, from "main" suppliers (trusted-expiry distributors
/ manufacturers), into apps.batches.PurchaseExpiryEntry.

Feeds the Purchase-Expiry Physical Audit report (near-expiry module) → which can
spawn a physical stock-count session.

Usage:
  python manage.py sync_purchase_expiry                       # last 3 years, all branches
  python manage.py sync_purchase_expiry --years 3
  python manage.py sync_purchase_expiry --from 2023-01 --to 2025-12
  python manage.py sync_purchase_expiry --branch 130
  python manage.py sync_purchase_expiry --categories OFFICIAL_DISTRIBUTOR,MANUFACTURER

Notes:
  • Reads SOFTECH read-only — no writeback. Writes only the PostgreSQL mirror.
  • Idempotent + re-runnable: after re-classifying more suppliers as "main"
    (re-run the procurement engine first), re-run this to pull the newly-included
    suppliers' history — the unique key inserts only the missing rows.
  • Marches MONTH BY MONTH; a multi-year stktrans scan is heavy — run off-hours.
  • Main suppliers come from the procurement SupplierSegmentation taxonomy, so
    run `run_procurement_engine` at least once first to classify suppliers.
"""
import datetime as _dt

from django.core.management.base import BaseCommand, CommandError


def _parse_ym(s, *, end=False):
    """'YYYY-MM' → date. end=True snaps to the last day of that month."""
    try:
        y, m = (int(x) for x in s.split('-'))
    except Exception:
        raise CommandError(f'Bad month {s!r} — use YYYY-MM')
    if end:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        return _dt.date(ny, nm, 1) - _dt.timedelta(days=1)
    return _dt.date(y, m, 1)


class Command(BaseCommand):
    help = ('Backfill purchase-with-expiry lines from main suppliers into the '
            'PurchaseExpiryEntry mirror (near-expiry physical audit engine).')

    def add_arguments(self, parser):
        parser.add_argument('--years', type=int, default=3,
                            help='Years back from today (default 3). Ignored if --from is given.')
        parser.add_argument('--from', dest='date_from',
                            help='Start month YYYY-MM (overrides --years).')
        parser.add_argument('--to', dest='date_to',
                            help='End month YYYY-MM inclusive (default: this month).')
        parser.add_argument('--branch', default='',
                            help='SOFTECH branch code to restrict to (default: all branches).')
        parser.add_argument('--categories', default='',
                            help='Comma-separated main-supplier category codes '
                                 '(default: OFFICIAL_DISTRIBUTOR,MANUFACTURER).')
        parser.add_argument('--timeout', type=int, default=300,
                            help='Per-query Sybase timeout in seconds (default 300).')

    def handle(self, *args, **opts):
        from apps.batches.models import PurchaseExpiryAuditRun
        from apps.batches.expiry_audit import run_backfill, MAIN_SUPPLIER_CATEGORIES

        today = _dt.date.today()

        # Resolve window.
        if opts.get('date_to'):
            window_to = _parse_ym(opts['date_to'], end=True)
        else:
            window_to = today
        if opts.get('date_from'):
            window_from = _parse_ym(opts['date_from'])
        else:
            try:
                window_from = window_to.replace(year=window_to.year - opts['years'])
            except ValueError:  # Feb 29 guard
                window_from = window_to.replace(year=window_to.year - opts['years'], day=28)
            window_from = window_from.replace(day=1)

        if window_from > window_to:
            raise CommandError('Empty window: --from is after --to.')

        categories = [c.strip() for c in opts['categories'].split(',') if c.strip()] \
            or list(MAIN_SUPPLIER_CATEGORIES)
        branch = (opts.get('branch') or '').strip()

        self.stdout.write(self.style.NOTICE(
            f'Purchase-expiry backfill: {window_from} → {window_to} | '
            f'branch={branch or "ALL"} | categories={",".join(categories)}'
        ))

        run = PurchaseExpiryAuditRun.objects.create(
            window_from=window_from, window_to=window_to,
            branch_scope=branch, categories=categories,
            triggered_by='sync_purchase_expiry',
        )
        try:
            stats = run_backfill(
                run, window_from, window_to,
                branch=branch or None, categories=categories,
                timeout=opts['timeout'],
            )
            run.finish('success')
        except Exception as e:
            run.finish('failed', error=str(e))
            raise CommandError(f'Backfill failed: {e}')

        self.stdout.write(self.style.SUCCESS(
            f'Done. suppliers={stats["suppliers"]} '
            f'fetched={stats["fetched"]:,} new_rows={stats["upserted"]:,} '
            f'(run #{run.pk})'
        ))
