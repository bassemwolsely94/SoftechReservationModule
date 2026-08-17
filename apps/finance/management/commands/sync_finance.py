"""
apps/finance/management/commands/sync_finance.py

Phase 9 — ETL sync command.

Usage
─────
    # Sync current month:
    python manage.py sync_finance

    # Sync a specific month:
    python manage.py sync_finance --year 2024 --month 3

    # Sync all months of a year:
    python manage.py sync_finance --year 2024 --full-year

    # Sync last N months:
    python manage.py sync_finance --months 6

SAFE TO RE-RUN — all writes use update_or_create.
"""

import datetime
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.finance.engine.sync_engine import FinanceSyncEngine
from apps.finance.models import FinanceSyncRun


class Command(BaseCommand):
    help = (
        "Phase 9 — Sync financial data from SOFTECH into PostgreSQL analytics layer.\n\n"
        "RECOMMENDED usage:\n"
        "  Fast (daily / backfill snapshots+expenses+treasury):\n"
        "    python manage.py sync_finance --months 12 --skip-coa --skip-journal --skip-inventory\n"
        "  Slow audit trail (run off-hours, last 3 months only):\n"
        "    python manage.py sync_finance --months 3 --skip-coa --skip-expenses --skip-treasury\n\n"
        "WARNING: running without --skip-journal processes ~60-100K stktrans rows per month\n"
        "via JPype (~720s/month). For 12 months that is ~2.4 hours."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year",  type=int, default=None,
                            help="Year to sync (default: current year)")
        parser.add_argument("--month", type=int, default=None,
                            help="Month to sync 1-12 (default: current month)")
        parser.add_argument("--full-year", dest="full_year", action="store_true",
                            default=False,
                            help="Sync all 12 months of --year")
        parser.add_argument("--months", dest="months", type=int, default=None,
                            help="Sync last N calendar months (e.g. --months 6)")
        parser.add_argument("--skip-journal", dest="skip_journal", action="store_true",
                            default=False,
                            help="Skip journal entry sync (faster -- snapshots only)")
        parser.add_argument("--skip-inventory", dest="skip_inventory", action="store_true",
                            default=False,
                            help="Skip inventory balance estimation (avoids full-table scan)")
        parser.add_argument("--skip-expenses", dest="skip_expenses", action="store_true",
                            default=False,
                            help="Skip expense record sync (dailyexpenses → ExpenseRecord)")
        parser.add_argument("--skip-treasury", dest="skip_treasury", action="store_true",
                            default=False,
                            help="Skip treasury payment sync (branchesales → TreasuryMovement)")
        parser.add_argument("--skip-coa", dest="skip_coa", action="store_true",
                            default=False,
                            help="Skip chart-of-accounts sync (accitems → Account)")

    def handle(self, *args, **options):
        today = datetime.date.today()
        year  = options["year"]  or today.year
        month = options["month"] or today.month

        # Build list of (year, month) pairs to sync
        periods: list[tuple[int, int]] = []

        if options["months"]:
            n = options["months"]
            cur = datetime.date(today.year, today.month, 1)
            for _ in range(n):
                periods.append((cur.year, cur.month))
                # subtract one month
                if cur.month == 1:
                    cur = datetime.date(cur.year - 1, 12, 1)
                else:
                    cur = datetime.date(cur.year, cur.month - 1, 1)
            periods.reverse()

        elif options["full_year"]:
            periods = [(year, m) for m in range(1, 13)]

        else:
            periods = [(year, month)]

        skip_journal    = options["skip_journal"]
        skip_inventory  = options["skip_inventory"]
        skip_expenses   = options["skip_expenses"]
        skip_treasury   = options["skip_treasury"]
        skip_coa        = options["skip_coa"]

        skip_labels = []
        if skip_journal:    skip_labels.append("no-journal")
        if skip_inventory:  skip_labels.append("no-inventory")
        if skip_expenses:   skip_labels.append("no-expenses")
        if skip_treasury:   skip_labels.append("no-treasury")
        if skip_coa:        skip_labels.append("no-coa")

        self.stdout.write(self.style.HTTP_INFO(
            f"\n  Finance Sync -- {len(periods)} period(s)"
            + (f" [{', '.join(skip_labels)}]" if skip_labels else " [full]")
            + "\n"
        ))

        total_start = time.time()
        all_stats: list[dict] = []

        # Open ONE shared Sybase connection for the entire run when processing
        # multiple months — avoids the JPype JVM connection overhead (which costs
        # ~1–2 s per open/close cycle) for every period in the loop.
        # A single-period run still benefits (the engine reuses it across steps).
        from config.sybase import get_sybase_connection
        shared_conn = None
        try:
            shared_conn = get_sybase_connection()
        except Exception as conn_err:
            self.stdout.write(self.style.WARNING(
                f"  [WARN] Could not open shared Sybase connection: {conn_err}\n"
                f"         Each period will open its own connection.\n"
            ))

        try:
            for yr, mo in periods:
                label = f"{yr}-{mo:02d}"
                self.stdout.write(f"  [{label}] Syncing ...", ending="")
                self.stdout.flush()

                sync_run = FinanceSyncRun.objects.create(
                    sync_type="incremental",
                    status="running",
                    started_at=timezone.now(),
                )

                t0 = time.time()
                try:
                    engine = FinanceSyncEngine(
                        year=yr, month=mo, sync_run=sync_run,
                        skip_coa=skip_coa,
                        skip_journal=skip_journal,
                        skip_inventory=skip_inventory,
                        skip_expenses=skip_expenses,
                        skip_treasury=skip_treasury,
                        sybase_conn=shared_conn,   # reuse across all months
                    )
                    result = engine.run()
                    elapsed = round(time.time() - t0, 1)
                    self.stdout.write(self.style.SUCCESS(
                        f"  [OK]  {elapsed}s  "
                        f"snaps={result.get('snapshots_created', 0)}+{result.get('snapshots_updated', 0)}  "
                        f"entries={result.get('journal_entries', 0)}  "
                        f"lines={result.get('journal_lines', 0)}  "
                        f"exp={result.get('expense_records', 0)}  "
                        f"tm={result.get('treasury_movements', 0)}  "
                        f"coa={result.get('coa_created', 0)}+{result.get('coa_updated', 0)}"
                    ))
                    all_stats.append({"period": label, **result})
                except Exception as exc:
                    elapsed = round(time.time() - t0, 1)
                    self.stdout.write(self.style.ERROR(f"  [FAIL]  {elapsed}s  {exc}"))
                    all_stats.append({"period": label, "status": "failed", "error": str(exc)})

        finally:
            if shared_conn is not None:
                try:
                    shared_conn.close()
                except Exception:
                    pass

        total_elapsed = round(time.time() - total_start, 1)
        failed = sum(1 for s in all_stats if s.get("status") == "failed")

        self.stdout.write(self.style.HTTP_INFO(
            f"\n  Total: {len(periods)} period(s) in {total_elapsed}s -- "
            f"{len(periods)-failed} OK, {failed} failed\n"
        ))
