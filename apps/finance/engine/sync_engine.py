"""
apps/finance/engine/sync_engine.py

Phase 9 — ETL orchestration.

Pulls financial data from SOFTECH (Sybase, SELECT-only) and writes to the
PostgreSQL analytics layer (FinancialSnapshot, JournalEntry, AccountBalance,
TreasuryMovement, ExpenseRecord, Account).

ABSOLUTE RULE: no INSERT / UPDATE / DELETE on any Sybase connection.

Entry point
───────────
    from apps.finance.engine.sync_engine import FinanceSyncEngine
    engine = FinanceSyncEngine(year=2024, month=3)
    engine.run()

The engine is designed to be safe to re-run for the same period — every
write uses update_or_create / get_or_create / bulk upsert, so duplicate
runs are idempotent.

Sync steps (in order)
──────────────────────
  Step 0 — Chart of Accounts (accitems → Account)          [skip_coa]
  Step 1 — FinancialPeriod get-or-create
  Step 2 — Branch P&L snapshot (stktrans → FinancialSnapshot)
  Step 3 — Journal entries (stktrans → JournalEntry/Line)   [skip_journal]
  Step 4 — Inventory balance estimate (stktrans → AccountBalance) [skip_inventory]
  Step 5 — Expenses (dailyexpenses → ExpenseRecord)          [skip_expenses]
  Step 6 — Treasury payments (branchesales → TreasuryMovement) [skip_treasury]
  Step 7 — Update snapshot with expense + treasury totals
  Step 8 — FinanceSyncRun audit record
"""

from __future__ import annotations

import decimal
import logging
from calendar import monthrange
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.finance.models import (
    Account,
    AccountBalance,
    ExpenseRecord,
    FinanceSyncRun,
    FinancialPeriod,
    FinancialSnapshot,
    JournalEntry,
    JournalLine,
    TreasuryMovement,
)
from apps.finance.queries.sybase_finance import (
    get_inventory_value_snapshot,
    get_monthly_branch_snapshot,
    get_purchases_by_month,
    get_sales_by_month,
    get_stktrans_doccodes,
    get_ytd_summary,
)

logger = logging.getLogger("finance.sync")

D = decimal.Decimal


# ── helpers ──────────────────────────────────────────────────────────────────

def _d(v: Any, fallback: str = "0") -> decimal.Decimal:
    """Safely convert any value to Decimal."""
    try:
        if v is None:
            return D(fallback)
        return D(str(v))
    except (decimal.InvalidOperation, ValueError):
        return D(fallback)


def _to_date(v: Any, year: int, month: int) -> date:
    """
    Convert a Sybase date value to a Python date object.
    """
    if v is None:
        return date(year, month, 1)
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        s = v.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s[:19], fmt[:len(fmt.replace("%z", ""))]).date()
            except ValueError:
                continue
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    return date(year, month, 1)


def _get_or_create_period(year: int, month: int) -> FinancialPeriod:
    last_day = monthrange(year, month)[1]
    period_start = date(year, month, 1)
    period_end   = date(year, month, last_day)
    label        = f"{year}-{month:02d}"

    obj, _ = FinancialPeriod.objects.get_or_create(
        year=year,
        month=month,
        period_type="month",
        defaults={
            "period_start": period_start,
            "period_end":   period_end,
            "label":        label,
        },
    )
    return obj


def _get_branch(softech_branch_id: str):
    """Return Branch or None — never raises."""
    try:
        from apps.branches.models import Branch
        return Branch.objects.get(softech_branch_id=str(softech_branch_id))
    except Exception:
        return None


def _build_branch_map() -> dict[str, Any]:
    """Pre-load all branches keyed by softech_branch_id for O(1) lookup."""
    try:
        from apps.branches.models import Branch
        return {b.softech_branch_id: b for b in Branch.objects.all()}
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# SYNC ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class FinanceSyncEngine:
    """
    Orchestrates one full monthly sync pass.

    Constructor flags (all default False = run all steps)
    ──────────────────────────────────────────────────────
    skip_coa       — skip chart-of-accounts sync (accitems → Account)
    skip_journal   — skip journal entry sync (stktrans → JournalEntry)
    skip_inventory — skip inventory balance estimation (avoids full-table scan)
    skip_expenses  — skip expense record sync (dailyexpenses → ExpenseRecord)
    skip_treasury  — skip treasury payment sync (branchesales → TreasuryMovement)

    Connection management
    ─────────────────────
    Pass ``sybase_conn`` to reuse an already-open connection (e.g. when the
    management command syncs multiple months in a loop).  The engine will NOT
    close an externally provided connection.  When ``sybase_conn`` is None the
    engine opens its own connection lazily on first Sybase query and closes
    it in ``run()``.
    """

    def __init__(
        self,
        year: int,
        month: int,
        sync_run: FinanceSyncRun | None = None,
        skip_coa: bool = False,
        skip_journal: bool = False,
        skip_inventory: bool = False,
        skip_expenses: bool = False,
        skip_treasury: bool = False,
        sybase_conn=None,
    ):
        self.year           = year
        self.month          = month
        self.sync_run       = sync_run
        self.skip_coa       = skip_coa
        self.skip_journal   = skip_journal
        self.skip_inventory = skip_inventory
        self.skip_expenses  = skip_expenses
        self.skip_treasury  = skip_treasury
        self._stats: dict[str, int] = {
            "coa_created":          0,
            "coa_updated":          0,
            "snapshots_created":    0,
            "snapshots_updated":    0,
            "journal_entries":      0,
            "journal_lines":        0,
            "account_balances":     0,
            "expense_records":      0,
            "treasury_movements":   0,
        }
        self._ext_conn  = sybase_conn
        self._own_conn  = None

    # ── Connection helpers ────────────────────────────────────────────────────

    def _get_conn(self):
        if self._ext_conn is not None:
            return self._ext_conn
        if self._own_conn is None:
            from config.sybase import get_sybase_connection
            self._own_conn = get_sybase_connection()
        return self._own_conn

    def _release_conn(self):
        if self._own_conn is not None:
            try:
                self._own_conn.close()
            except Exception:
                pass
            self._own_conn = None

    # ── public ───────────────────────────────────────────────────────────────

    def run(self) -> dict:
        logger.info(f"[FinanceSyncEngine] Starting sync {self.year}-{self.month:02d}")

        try:
            # Step 0: Chart of accounts (global, not period-specific)
            if not self.skip_coa:
                try:
                    self._sync_chart_of_accounts()
                except Exception as e:
                    logger.warning(f"  [Step 0] COA sync failed (non-fatal): {e}")

            # Step 1: Ensure period exists
            period = _get_or_create_period(self.year, self.month)

            # Step 2: Branch P&L snapshots (stktrans GROUP BY)
            self._sync_snapshots(period)

            # Step 3: Journal entries (detailed stktrans lines)
            if not self.skip_journal:
                try:
                    self._sync_journal_entries(period)
                except Exception as e:
                    logger.warning(f"  [Step 3] Journal sync failed (non-fatal): {e}")

            # Step 4: Inventory balance estimates
            if not self.skip_inventory:
                try:
                    self._sync_inventory_balances(period)
                except Exception as e:
                    logger.warning(f"  [Step 4] Inventory balance sync failed (non-fatal): {e}")

            # Step 5: Expense records
            if not self.skip_expenses:
                try:
                    self._sync_expenses(period)
                except Exception as e:
                    logger.warning(f"  [Step 5] Expense sync failed (non-fatal): {e}")

            # Step 6: Treasury payments from branchesales
            if not self.skip_treasury:
                try:
                    self._sync_treasury_payments(period)
                except Exception as e:
                    logger.warning(f"  [Step 6] Treasury sync failed (non-fatal): {e}")

            # Step 7: Update snapshot with expense + treasury data now in DB
            if not (self.skip_expenses and self.skip_treasury):
                try:
                    self._update_snapshot_with_expenses(period)
                except Exception as e:
                    logger.warning(f"  [Step 7] Snapshot expense update failed (non-fatal): {e}")

            if self.sync_run:
                self.sync_run.mark_done(success=True, records=self._stats)

            logger.info(f"[FinanceSyncEngine] Done — stats: {self._stats}")
            return {"status": "success", **self._stats}

        except Exception as exc:
            logger.exception(f"[FinanceSyncEngine] Failed: {exc}")
            if self.sync_run:
                self.sync_run.status = "failed"
                self.sync_run.errors = {"error": str(exc)}
                self.sync_run.save(update_fields=["status", "errors"])
            raise

        finally:
            self._release_conn()

    # ── step 0: chart of accounts ─────────────────────────────────────────────

    def _sync_chart_of_accounts(self) -> None:
        """
        Sync all 148 accitems rows into the Account model.

        Two-pass approach for hierarchy:
          Pass 1: upsert all accounts without parent FK
          Pass 2: set parent FK for non-root accounts
        """
        from apps.finance.queries.sybase_accounting import get_chart_of_accounts_structured

        rows = get_chart_of_accounts_structured(conn=self._get_conn())
        if not rows or (len(rows) == 1 and '_error' in rows[0]):
            logger.warning(f"  COA: no rows returned ({rows[0].get('_error', 'empty')})")
            return

        logger.info(f"  COA: syncing {len(rows)} accounts from accitems")

        # Pass 1: upsert all accounts (no parent FK yet)
        # Use `code` as the lookup key since it has unique=True on the model.
        # softech_code is blank=True without unique=True, so it can't be used
        # as the update_or_create lookup field (would raise MultipleObjectsReturned
        # if duplicates exist from manual entries).
        with transaction.atomic():
            for row in rows:
                code = str(row.get('accitemcode') or '').strip()
                if not code:
                    continue
                name_ar = str(row.get('accitemname') or '').strip()
                is_leaf = str(row.get('acclast') or '0').strip() == '1'

                obj, created = Account.objects.update_or_create(
                    code=code,          # unique field — safe as lookup key
                    defaults={
                        'softech_code': code,
                        'name':         name_ar or code,
                        'name_ar':      name_ar,
                        'account_type': row.get('_account_type', 'unknown'),
                        'nature':       row.get('_nature', 'debit'),
                        'level':        row.get('_level', 1),
                        'is_leaf':      is_leaf,
                        'is_active':    True,
                        'synced_at':    timezone.now(),
                    },
                )
                if created:
                    self._stats["coa_created"] += 1
                else:
                    self._stats["coa_updated"] += 1

        # Pass 2: set parent FK (requires all accounts to exist first)
        all_codes = [str(r.get('accitemcode') or '') for r in rows if r.get('accitemcode')]
        code_to_pk: dict[str, int] = {
            a.code: a.pk
            for a in Account.objects.filter(code__in=all_codes)
        }

        with transaction.atomic():
            for row in rows:
                parent_code = row.get('_parent_code')
                if not parent_code:
                    continue
                code = str(row.get('accitemcode') or '').strip()
                own_pk   = code_to_pk.get(code)
                parent_pk = code_to_pk.get(parent_code)
                if own_pk and parent_pk:
                    Account.objects.filter(pk=own_pk).update(parent_id=parent_pk)

        logger.info(
            f"  COA: {self._stats['coa_created']} created, "
            f"{self._stats['coa_updated']} updated"
        )

    # ── step 2-3: financial snapshots ────────────────────────────────────────

    def _sync_snapshots(self, period: FinancialPeriod) -> None:
        rows = get_monthly_branch_snapshot(self.year, self.month, conn=self._get_conn())
        logger.info(f"  Got {len(rows)} branch snapshot rows from SOFTECH")

        with transaction.atomic():
            # Company-wide aggregate snapshot (branch=None)
            self._upsert_snapshot(period, branch=None, branch_rows=rows)

            # Per-branch snapshots
            seen_ids: set[str] = set()
            for row in rows:
                bid = str(row.get("branchcode") or "")
                if bid in seen_ids:
                    continue
                seen_ids.add(bid)
                branch = _get_branch(bid)
                branch_data = [r for r in rows if str(r.get("branchcode") or "") == bid]
                self._upsert_snapshot(period, branch=branch, branch_rows=branch_data)

    def _upsert_snapshot(
        self,
        period: FinancialPeriod,
        branch,
        branch_rows: list[dict],
    ) -> None:
        total_purchases_gross  = sum(_d(r.get("total_purchases_gross"))   for r in branch_rows)
        total_purchases_net    = sum(_d(r.get("total_purchases_net"))     for r in branch_rows)
        total_purch_returns    = sum(_d(r.get("total_purchase_returns"))  for r in branch_rows)
        total_sales_gross      = sum(_d(r.get("total_sales_gross"))       for r in branch_rows)
        total_sales_net        = sum(_d(r.get("total_sales_net"))         for r in branch_rows)
        total_sales_returns    = sum(_d(r.get("total_sales_returns"))     for r in branch_rows)
        total_tax              = sum(_d(r.get("total_tax"))               for r in branch_rows)

        net_purchases = total_purchases_net - total_purch_returns
        net_sales     = total_sales_net     - total_sales_returns

        gross_revenue    = total_sales_gross
        returns_value    = total_sales_returns
        net_revenue      = net_sales
        cogs             = net_purchases
        gross_profit     = net_revenue - cogs

        _MARGIN_CAP = D("99999.99")
        if net_revenue > 0:
            raw_margin = (gross_profit / net_revenue * D("100")).quantize(D("0.01"))
            gross_margin_pct = (
                raw_margin if abs(raw_margin) <= _MARGIN_CAP else D("0")
            )
        else:
            gross_margin_pct = D("0")

        defaults = {
            "gross_revenue":           gross_revenue,
            "returns_value":           returns_value,
            "net_revenue":             net_revenue,
            "cogs":                    cogs,
            "gross_profit":            gross_profit,
            "gross_margin_pct":        gross_margin_pct,
            "total_purchases":         total_purchases_gross,
            "total_purchase_returns":  total_purch_returns,
            "net_purchases":           net_purchases,
            "data_sources":            ["stktrans"],
            "is_complete":             True,
        }

        snap, created = FinancialSnapshot.objects.update_or_create(
            period=period,
            branch=branch,
            defaults=defaults,
        )

        if created:
            self._stats["snapshots_created"] += 1
        else:
            self._stats["snapshots_updated"] += 1

    # ── step 3: journal entries ───────────────────────────────────────────────

    def _sync_journal_entries(self, period: FinancialPeriod) -> None:
        purchase_rows = get_purchases_by_month(self.year, self.month, conn=self._get_conn())
        sales_rows    = get_sales_by_month(self.year, self.month, conn=self._get_conn())

        all_rows = [
            (r, "purchase") for r in purchase_rows
        ] + [
            (r, "sale") for r in sales_rows
        ]

        docs: dict[tuple, list] = {}
        for row, entry_type in all_rows:
            key = (str(row.get("docnumber")), str(row.get("branchcode") or ""), entry_type)
            docs.setdefault(key, []).append(row)

        created_entries = 0
        created_lines   = 0

        with transaction.atomic():
            for (docno, branch_id_str, entry_type), lines in docs.items():
                branch = _get_branch(branch_id_str)
                first  = lines[0]
                total_debit  = sum(_d(r.get("gross_amount") or r.get("gross_revenue")) for r in lines)
                total_credit = total_debit

                entry, _ = JournalEntry.objects.update_or_create(
                    softech_number=docno,
                    entry_type=entry_type,
                    defaults={
                        "entry_date":   _to_date(first.get("docdate"), self.year, self.month),
                        "branch":       branch,
                        "total_debit":  total_debit,
                        "total_credit": total_credit,
                        "period":       period,
                    },
                )
                created_entries += 1

                entry.lines.all().delete()

                bulk_lines = []
                for row in lines:
                    gross = _d(row.get("gross_amount") or row.get("gross_revenue"))
                    bulk_lines.append(JournalLine(
                        entry=entry,
                        debit=gross,
                        credit=D("0"),
                        party_code=str(row.get("itemcode") or ""),
                    ))
                JournalLine.objects.bulk_create(bulk_lines)
                created_lines += len(bulk_lines)

        self._stats["journal_entries"] += created_entries
        self._stats["journal_lines"]   += created_lines
        logger.info(f"  Journal: {created_entries} entries, {created_lines} lines")

    # ── step 4: inventory balances ────────────────────────────────────────────

    def _sync_inventory_balances(self, period: FinancialPeriod) -> None:
        rows = get_inventory_value_snapshot(self.year, self.month, conn=self._get_conn())

        inv_account, _ = Account.objects.get_or_create(
            code="INV-EST",
            defaults={
                "name":         "Inventory Value (Estimated)",
                "account_type": "asset",
                "nature":       "debit",
                "level":        1,
                "is_leaf":      True,
            },
        )

        with transaction.atomic():
            for row in rows:
                branch = _get_branch(str(row.get("branchcode") or ""))
                value  = _d(row.get("est_inventory_value"))

                AccountBalance.objects.update_or_create(
                    account=inv_account,
                    period=period,
                    branch=branch,
                    defaults={"closing_balance": value},
                )
                self._stats["account_balances"] += 1

        logger.info(f"  Inventory balances: {len(rows)} branch(es) updated")

    # ── step 5: expense records ───────────────────────────────────────────────

    def _sync_expenses(self, period: FinancialPeriod) -> None:
        """
        Sync dailyexpenses (joined with expenses master) → ExpenseRecord.

        Strategy: delete all existing ExpenseRecord rows for this period +
        source_table='dailyexpenses', then bulk-create fresh rows.
        This avoids the need for a natural PK in dailyexpenses.
        """
        from apps.finance.queries.sybase_accounting import (
            get_dailyexpenses_with_master_by_month,
        )

        rows = get_dailyexpenses_with_master_by_month(
            self.year, self.month, conn=self._get_conn()
        )

        if rows and '_error' in rows[0]:
            logger.warning(f"  Expenses: query failed — {rows[0]['_error']}")
            return

        logger.info(f"  Expenses: {len(rows)} rows from dailyexpenses")

        branch_map = _build_branch_map()

        # Pre-load accitems account map for linking account_code
        account_code_set: set[str] = set()
        for row in rows:
            code = str(row.get('expaccitemcode') or '').strip()
            if code:
                account_code_set.add(code)

        with transaction.atomic():
            # Delete existing expense records for this period from dailyexpenses source
            deleted_count = ExpenseRecord.objects.filter(
                period=period,
                source_table='dailyexpenses',
            ).delete()[0]
            if deleted_count:
                logger.info(f"  Expenses: deleted {deleted_count} stale records before re-sync")

            bulk_records = []
            for row in rows:
                branch_code = str(row.get('branchcode') or '').strip()
                branch = branch_map.get(branch_code)

                expense_date_raw = row.get('expensedate')
                expense_date = _to_date(expense_date_raw, self.year, self.month)

                amount = _d(row.get('expvalue'))
                if amount <= D("0"):
                    continue

                category    = str(row.get('_category') or 'other')
                sub_cat     = str(row.get('expdescr') or '').strip()[:100]
                description = str(row.get('expcomment') or row.get('expdescr') or '').strip()[:500]
                cost_center = str(row.get('costcentercode') or '').strip()
                acc_code    = str(row.get('expaccitemcode') or '').strip()

                # softech_ref: use cheqsno if available, else build a positional ref
                cheqsno = str(row.get('cheqsno') or '').strip()
                softech_ref = f"EXP-{cheqsno}" if cheqsno else ''

                bulk_records.append(ExpenseRecord(
                    softech_ref=softech_ref,
                    expense_date=expense_date,
                    category=category,
                    sub_category=sub_cat,
                    branch=branch,
                    amount=amount,
                    description=description,
                    account_code=acc_code,
                    cost_center=cost_center,
                    period=period,
                    source_table='dailyexpenses',
                ))

            if bulk_records:
                ExpenseRecord.objects.bulk_create(bulk_records, batch_size=1000)
                self._stats["expense_records"] += len(bulk_records)

        logger.info(f"  Expenses: {self._stats['expense_records']} records created")

    # ── step 6: treasury payments ─────────────────────────────────────────────

    def _sync_treasury_payments(self, period: FinancialPeriod) -> None:
        """
        Sync branchesales (aggregated monthly by branch × payment_type)
        → TreasuryMovement.

        One TreasuryMovement per (branch, paymenttype, month) — idempotent
        via softech_number = 'BSALES-{year}-{month}-{branch}-{paytype}'.

        Also syncs actual bank cheques (cheqtype='20') from the cheques table.
        """
        from apps.finance.queries.sybase_accounting import (
            get_branchesales_monthly_aggregated,
            get_actual_cheques_by_month,
            get_paymenttypes_dict,
            get_banks_balance_dict,
        )

        branch_map = _build_branch_map()

        # Load lookup tables once (small, fast)
        paytypes_master = {}
        bank_names: dict[str, str] = {}
        try:
            paytypes_master = get_paymenttypes_dict(conn=self._get_conn())
        except Exception:
            pass
        try:
            bank_names = get_banks_balance_dict(conn=self._get_conn())
        except Exception:
            pass

        # ── 6a: branchesales aggregates ───────────────────────────────────────
        agg_rows = get_branchesales_monthly_aggregated(
            self.year, self.month, conn=self._get_conn()
        )

        if agg_rows and '_error' in agg_rows[0]:
            logger.warning(f"  Treasury: branchesales query failed — {agg_rows[0]['_error']}")
            agg_rows = []

        logger.info(f"  Treasury: {len(agg_rows)} payment aggregates from branchesales")

        from apps.finance.queries.sybase_accounting import _map_payment_method

        created_tm = 0
        with transaction.atomic():
            for row in agg_rows:
                branch_code = str(row.get('branchcode') or '').strip()
                paytype     = str(row.get('paymenttype') or '').strip()
                total       = _d(row.get('total_payments'))

                if total <= D("0"):
                    continue

                branch = branch_map.get(branch_code)
                method = _map_payment_method(paytype, paytypes_master)

                softech_number = (
                    f"BSALES-{self.year}-{self.month:02d}-{branch_code}-{paytype}"
                )

                # Payment type description for the description field
                type_descr = paytypes_master.get(paytype, f"نوع{paytype}")

                _, created = TreasuryMovement.objects.update_or_create(
                    softech_number=softech_number,
                    defaults={
                        "movement_date":  date(self.year, self.month, 1),
                        "movement_type":  "receipt",
                        "direction":      "in",
                        "payment_method": method,
                        "branch":         branch,
                        "amount":         total,
                        "description":    f"مبيعات {type_descr} — {self.year}/{self.month:02d}",
                        "period":         period,
                        "source_table":   "branchesales",
                        "party_type":     "customer",
                    },
                )
                created_tm += 1

        self._stats["treasury_movements"] += created_tm
        logger.info(f"  Treasury: {created_tm} payment movements upserted")

        # ── 6b: actual bank cheques (cheqtype='20') ───────────────────────────
        cheque_rows = get_actual_cheques_by_month(
            self.year, self.month, conn=self._get_conn()
        )

        if cheque_rows and '_error' in cheque_rows[0]:
            logger.warning(f"  Treasury: cheques query failed — {cheque_rows[0]['_error']}")
            cheque_rows = []

        logger.info(f"  Treasury: {len(cheque_rows)} actual cheques")

        created_cheques = 0
        with transaction.atomic():
            for row in cheque_rows:
                cheqsno   = str(row.get('cheqsno') or '').strip()
                cheqvalue = _d(row.get('cheqvalue'))

                if cheqvalue <= D("0") or not cheqsno:
                    continue

                cheq_date   = _to_date(row.get('cheqdate'), self.year, self.month)
                branch_code = str(row.get('branchcode') or '').strip()
                branch      = branch_map.get(branch_code)
                bankcode    = str(row.get('bankcode') or '').strip()
                bank_name   = bank_names.get(bankcode, '')
                direction   = str(row.get('_direction') or 'in')

                softech_number = f"CHQ-{cheqsno}"

                _, created = TreasuryMovement.objects.update_or_create(
                    softech_number=softech_number,
                    defaults={
                        "movement_date":  cheq_date,
                        "movement_type":  "payment" if direction == "out" else "receipt",
                        "direction":      direction,
                        "payment_method": "cheque",
                        "account_code":   bankcode,
                        "branch":         branch,
                        "amount":         cheqvalue,
                        "cheque_number":  cheqsno,
                        "cheque_date":    cheq_date,
                        "bank_name":      bank_name,
                        "party_code":     str(row.get('personcode') or ''),
                        "period":         period,
                        "source_table":   "cheques",
                    },
                )
                created_cheques += 1

        self._stats["treasury_movements"] += created_cheques
        logger.info(f"  Treasury cheques: {created_cheques} records upserted")

    # ── step 7: update snapshot with expense + treasury totals ────────────────

    def _update_snapshot_with_expenses(self, period: FinancialPeriod) -> None:
        """
        After expenses and treasury are in the DB, update FinancialSnapshot
        fields that depend on them:
          total_expenses, payroll_expenses, rent_expenses, utility_expenses,
          other_expenses, operating_profit, net_profit, net_margin_pct,
          cash_inflow, cash_outflow, net_cash_flow.

        Data_sources list is extended to include the new sources.
        """
        from django.db.models import Sum, Q

        # ── Expense totals by category ─────────────────────────────────────────
        exp_qs = ExpenseRecord.objects.filter(period=period)

        def _exp_sum(qs) -> decimal.Decimal:
            v = qs.aggregate(t=Sum('amount'))['t']
            return _d(v)

        total_expenses   = _exp_sum(exp_qs)
        payroll_exp      = _exp_sum(exp_qs.filter(category='payroll'))
        rent_exp         = _exp_sum(exp_qs.filter(category='rent'))
        utility_exp      = _exp_sum(exp_qs.filter(
            category__in=['utilities', 'fuel']
        ))
        other_exp        = total_expenses - payroll_exp - rent_exp - utility_exp

        # ── Treasury totals ────────────────────────────────────────────────────
        tm_qs    = TreasuryMovement.objects.filter(period=period)
        inflow   = _exp_sum(tm_qs.filter(direction='in'))
        outflow  = _exp_sum(tm_qs.filter(direction='out'))
        net_cash = inflow - outflow

        # Update each existing snapshot for this period
        snaps = FinancialSnapshot.objects.filter(period=period)

        for snap in snaps:
            # For branch-specific snapshots, filter by branch; for consolidated use all
            if snap.branch is not None:
                branch_exp_qs = exp_qs.filter(branch=snap.branch)
                branch_tm_qs  = tm_qs.filter(branch=snap.branch)
                snap_total_exp  = _exp_sum(branch_exp_qs)
                snap_payroll    = _exp_sum(branch_exp_qs.filter(category='payroll'))
                snap_rent       = _exp_sum(branch_exp_qs.filter(category='rent'))
                snap_utility    = _exp_sum(branch_exp_qs.filter(
                    category__in=['utilities', 'fuel']
                ))
                snap_other      = snap_total_exp - snap_payroll - snap_rent - snap_utility
                snap_inflow     = _exp_sum(branch_tm_qs.filter(direction='in'))
                snap_outflow    = _exp_sum(branch_tm_qs.filter(direction='out'))
            else:
                snap_total_exp = total_expenses
                snap_payroll   = payroll_exp
                snap_rent      = rent_exp
                snap_utility   = utility_exp
                snap_other     = other_exp
                snap_inflow    = inflow
                snap_outflow   = outflow

            snap_net_cash     = snap_inflow - snap_outflow
            operating_profit  = snap.gross_profit - snap_total_exp
            net_profit        = operating_profit
            net_revenue       = snap.net_revenue
            net_margin        = (
                (net_profit / net_revenue * D("100")).quantize(D("0.01"))
                if net_revenue > 0 else D("0")
            )

            # Extend data_sources
            sources = list(snap.data_sources or [])
            for src in ('dailyexpenses', 'branchesales'):
                if src not in sources:
                    sources.append(src)

            FinancialSnapshot.objects.filter(pk=snap.pk).update(
                total_expenses=snap_total_exp,
                payroll_expenses=snap_payroll,
                rent_expenses=snap_rent,
                utility_expenses=snap_utility,
                other_expenses=snap_other,
                operating_profit=operating_profit,
                net_profit=net_profit,
                net_margin_pct=net_margin,
                cash_inflow=snap_inflow,
                cash_outflow=snap_outflow,
                net_cash_flow=snap_net_cash,
                data_sources=sources,
            )

        logger.info(
            f"  Snapshot enriched: {snaps.count()} snapshots updated with "
            f"expenses ({total_expenses:,.0f}) + treasury (in={inflow:,.0f} out={outflow:,.0f})"
        )
