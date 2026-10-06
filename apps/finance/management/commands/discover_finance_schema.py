"""
apps/finance/management/commands/discover_finance_schema.py

Phase 0 — SOFTECH schema discovery.

Usage
─────
    # Full discovery scan (first run or refresh):
    python manage.py discover_finance_schema

    # Re-inspect a single table already in the dictionary:
    python manage.py discover_finance_schema --table stktrans

    # Lower the minimum relevance score (default 3) to cast a wider net:
    python manage.py discover_finance_schema --min-score 1

    # Print the table without saving:
    python manage.py discover_finance_schema --dry-run

This command is SAFE to re-run.
- New tables are created.
- Existing rows are updated (row_count, columns, sample_rows, inferred_purpose).
- is_confirmed / sync_enabled / notes are NEVER overwritten — these are
  admin-managed fields that a human sets after reviewing the schema.

ABSOLUTE RULE: This command only SELECTs from SOFTECH (Sybase).
               It writes only to PostgreSQL (FinanceSchemaTable).
"""
import sys
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.finance.models import FinanceSchemaTable, FinanceSyncRun
from apps.finance.queries.sybase_discovery import (
    discover_financial_tables,
    get_known_table_info,
)


class Command(BaseCommand):
    help = "Phase 0 — Discover financial tables in SOFTECH (SELECT-only)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--table",
            dest="table",
            default=None,
            help="Re-inspect a single named table instead of running a full scan.",
        )
        parser.add_argument(
            "--min-score",
            dest="min_score",
            type=int,
            default=3,
            help="Minimum relevance score for a table to be included (default: 3).",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=False,
            help="Print results but do not write to the database.",
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _progress(self, current: int, total: int, table_name: str) -> None:
        pct = int(current / total * 100)
        self.stdout.write(
            f"\r  Scanning {current}/{total} ({pct}%)  {table_name:<40}",
            ending="",
        )
        self.stdout.flush()

    def _print_table_row(self, t: dict) -> None:
        self.stdout.write(
            f"  {'['+t['category']+']':<14}  "
            f"score={t['score']:<3}  "
            f"rows={t['row_count']:<10}  "
            f"{t['table_name']:<35}  "
            f"{t['inferred_purpose']}"
        )

    def _upsert(self, t: dict, dry_run: bool) -> tuple[bool, bool]:
        """
        Upsert one discovered table into FinanceSchemaTable.
        Returns (created, updated).
        Admin fields (is_confirmed, sync_enabled, notes) are never touched.
        """
        if dry_run:
            return False, False

        obj, created = FinanceSchemaTable.objects.get_or_create(
            table_name=t["table_name"],
            defaults={
                "inferred_purpose": t["inferred_purpose"],
                "row_count":        t["row_count"],
                "columns":          t["columns"],
                "sample_rows":      t["sample_rows"],
                "category":         t["category"],
                "discovered_at":    timezone.now(),
            },
        )

        if not created:
            # Refresh metadata; never touch is_confirmed / sync_enabled / notes
            obj.inferred_purpose = t["inferred_purpose"]
            obj.row_count        = t["row_count"]
            obj.columns          = t["columns"]
            obj.sample_rows      = t["sample_rows"]
            obj.category         = t["category"]
            obj.discovered_at    = timezone.now()
            obj.save(update_fields=[
                "inferred_purpose", "row_count", "columns",
                "sample_rows", "category", "discovered_at",
            ])
            return False, True

        return True, False

    # ── main handler ─────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        table_filter = options["table"]
        min_score    = options["min_score"]
        dry_run      = options["dry_run"]

        self.stdout.write(self.style.HTTP_INFO(
            "\n══════════════════════════════════════════\n"
            "  Finance Module — Phase 0: Schema Discovery\n"
            "══════════════════════════════════════════"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("  [DRY RUN] — no changes will be written\n"))

        sync_run = None
        if not dry_run:
            sync_run = FinanceSyncRun.objects.create(
                sync_type="discovery",
                status="running",
                started_at=timezone.now(),
            )

        start = time.time()

        try:
            # ── Single table mode ─────────────────────────────────────────
            if table_filter:
                self.stdout.write(f"  Re-inspecting table: {table_filter}")
                info = get_known_table_info(table_filter)
                if info is None:
                    self.stderr.write(self.style.ERROR(
                        f"  Table '{table_filter}' not found or not accessible."
                    ))
                    if sync_run:
                        sync_run.status = "failed"
                        sync_run.errors = {"error": f"Table '{table_filter}' not found"}
                        sync_run.save(update_fields=["status", "errors"])
                    sys.exit(1)

                info["score"] = 99  # bypass scoring for explicit lookup
                self._print_table_row(info)
                created, updated = self._upsert(info, dry_run)
                label = "created" if created else ("updated" if updated else "no-op")
                self.stdout.write(self.style.SUCCESS(f"\n  Done: {label}"))
                results = [info]

            # ── Full scan mode ────────────────────────────────────────────
            else:
                self.stdout.write(f"  min_score={min_score} — scanning all SOFTECHDB9 user tables …\n")

                results = discover_financial_tables(
                    min_score=min_score,
                    progress_callback=self._progress,
                )
                self.stdout.write("")  # newline after progress bar

                if not results:
                    self.stdout.write(self.style.WARNING(
                        "  No financial tables found. "
                        "Try lowering --min-score."
                    ))
                else:
                    self.stdout.write(
                        f"\n  Found {len(results)} relevant table(s):\n"
                    )
                    self.stdout.write(
                        f"  {'[category]':<14}  "
                        f"{'score':<8}  "
                        f"{'rows':<12}  "
                        f"{'table_name':<35}  "
                        f"inferred_purpose"
                    )
                    self.stdout.write("  " + "─" * 120)

                    created_count  = 0
                    updated_count  = 0
                    for t in results:
                        self._print_table_row(t)
                        created, updated = self._upsert(t, dry_run)
                        if created:
                            created_count += 1
                        elif updated:
                            updated_count += 1

                    self.stdout.write("")
                    self.stdout.write(self.style.SUCCESS(
                        f"  Saved:  {created_count} new  |  {updated_count} updated"
                    ))

            # ── Finalize sync run ─────────────────────────────────────────
            elapsed = round(time.time() - start, 1)
            if sync_run:
                sync_run.mark_done(
                    success=True,
                    records={
                        "tables_found":   len(results),
                        "elapsed_seconds": elapsed,
                    },
                )

            self.stdout.write(self.style.SUCCESS(
                f"\n  ✓ Phase 0 complete in {elapsed}s\n"
            ))

            # ── Next-step guidance ────────────────────────────────────────
            if not dry_run and results:
                self.stdout.write(self.style.HTTP_INFO(
                    "  Next steps:\n"
                    "  1. Run: python manage.py shell\n"
                    "     >>> from apps.finance.models import FinanceSchemaTable\n"
                    "     >>> FinanceSchemaTable.objects.all().values('table_name','category','row_count')\n"
                    "  2. In Django admin → Finance → Schema Tables:\n"
                    "     - Review each table.\n"
                    "     - Set is_confirmed=True for tables you want to sync.\n"
                    "     - Set sync_enabled=True to include in ETL.\n"
                    "  3. Then run: python manage.py sync_finance\n"
                ))

        except Exception as exc:
            elapsed = round(time.time() - start, 1)
            self.stderr.write(self.style.ERROR(f"\n  ✗ Discovery failed after {elapsed}s: {exc}"))
            if sync_run:
                sync_run.status = "failed"
                sync_run.errors = {"error": str(exc)}
                sync_run.save(update_fields=["status", "errors"])
            raise
