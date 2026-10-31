# 06 · SPEC P-43 — Finance screens: no stale numbers

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.

**Owner input**
- Finance uses the **gross-profit** and **expense** pages (branch expenses).
- **Cash flow** is not used; it is replaced by P-40.
- HQ expenses are in Excel. A full accounting module comes later (P-44, deferred).

## 1. Problem (measured)

- The journal and treasury mirrors stop at **May 2026** (journal 2026-05-22, treasury 2026-05-30). The scheduler only
  refreshes the P&L snapshot every 30 min. Journal, inventory, expenses and treasury need a manual
  `sync_finance --months 3` (`apps/sync/tasks.py`).
- `analytics` values "capital tied" at selling price. That is handled in P-35, not here.

## 2. Scope

1. **Schedule** `sync_finance --months 3` nightly at 02:15, which reads SOFTECH SELECT-only, using the P-56
   reconnect/retry rule.
2. **Freshness:** add domains `finance_pl`, `finance_expenses` and `finance_journal` to `apps/sync/freshness.py`
   `DOMAINS`. Show the existing `DataFreshnessBar` (domains mode) on:
   - `/finance` (gross profit);
   - the expense pages;
   - the A/P reconciliation page;
   - a forced-refresh button per the project convention.
3. **Hide cash flow:** the `/finance/cashflow` route is removed from the sidebar and finance tabs, and redirects to the
   P-40 view when that exists. Until then it shows a "replaced by the 13-week cash view (coming)" note.
4. **External payments module** (`/payments`, 0 rows): hidden from the sidebar unless finance asks for it. The code is
   kept.

## 3. Acceptance criteria

- The scheduler registers `finance_nightly_sync` (scheduler test).
- The freshness API returns the three new domains with `stale=True` when the last run is older than 3× cadence (test).
- The cash-flow route is no longer in the sidebar. Its URL redirects or shows the note.
- Help updated for `/finance` and the expenses page (freshness bar, cash flow removed); `test_help.py` passes.

## 4. Measurement

- Journal and treasury data age in days: baseline ≈150, target ≤ 1.
