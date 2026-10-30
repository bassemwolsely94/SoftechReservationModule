# 06 · SPEC P-40 — 13-week cash view

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
Read-only toward SOFTECH. Reads from P-41 (contract receivables) and P-42 (supplier terms), so build those first.
Replaces the retired `/finance/cashflow` page (P-43).

**Owner input** (ledger row P-40; overrides the backlog card)
- **Audience:** all finance users (four named staff) and all admins, including the owner.
- Contract inflows use **measured settlement per contract** (P-41: 4227 ≈44 days, 4288 ≈42 days).
- Supplier outflows use **terms per supplier × category** (P-42).
- Add an **early-pay foregone** line: what early payment would have earned (P-42).
- **Fixed outflows are a finance input** (salaries, rent and so on). The expense mirror does not cover HQ expenses,
  which are in Excel.
- The **P-34 purchase budget comes later**. Until then, a run-rate plus a "what if" input.
- Finance data is all-branch only (security Batch 5, B-1).

## 1. Problem (measured)

- The business is cash-constrained (owner). Purchase cover, supplier payments and collections are decided without one
  forward view of cash.
- The cash-relevant facts exist only in pieces:
  - **post-dated supplier cheques** already written: Nov 2.31M, Dec 1.06M (A/P mirror);
  - open payables with **no due dates** (0 of 6,919 invoices in 90 days), ≈4.5–6.5M paid per month;
  - **contract receivables not mirrored**: ≈5.4M tied up at ≈43 days;
  - sales by channel per 90 days: cash (91) 9.41M, delivery (90) 2.87M, contracts (10) 11.26M.
- The old cash-flow page read the treasury mirror, which stopped at May 2026. It was unused and is retired
  (`frontend/src/pages/CashFlowRetired.jsx`, P-43).
- The cheque planner (`apps/cheques`) has 0 plans. It duplicates cheques the mirror already holds.

## 2. Scope

**1. Finance inputs** (new models in `apps/finance`, each change audited):
- `CashOpeningBalance`: `as_of` (date), `amount`, `note` (which boxes and banks), `entered_by`, `entered_at`.
  Entered weekly. The latest one on or before the view date is the opening point. This also gives the "actual" for
  measurement (§4).
- `FixedOutflow`:
  - `label`, `category` (salaries / rent / utilities / taxes / loans / other), `amount`;
  - `frequency` (`weekly` / `monthly` / `one_off`), `day_of_month` or `date`, `start`, `end` (nullable);
  - `is_active`, `entered_by`.
- Audit: `apps/audit.AuditLog`, new action `finance_cash_input_changed` with before/after. The new choice needs an
  `audit` migration.

**2. Engine** — new `apps/finance/cash_view.py`, PostgreSQL only, `Decimal` throughout, no SOFTECH call.
`build_cash_view(as_of, weeks=13, purchase_budget_weekly=None) -> dict`.
- Weeks start Sunday (first banking day; see `apps/cheques/engine.py`). Week 1 contains `as_of`.
- Dated items that fall on a non-banking day move with `cheques.engine.next_banking_day`.
- Every line carries:
  - `key`, `label_ar`;
  - `source` (`softech_mirror` / `finance_input` / `estimate`);
  - `freshness_domain`;
  - `low` / `base` / `high` per week.

| # | Line | Source | Rule |
|---|---|---|---|
| **In** | | | |
| I1 | Cash and delivery sales «مبيعات نقدي وتوصيل» | `customers.PurchaseHistory` (`sales_channel` = invoice-level `stktransm.ptclassifcode`) | Channels from SystemSetting `cash_view_cash_channels` (default `91,90`). Weekly net = 115 − 30. Base = mean of the last 8 complete weeks; low = min, high = max of those weeks |
| I2 | Contract collections «تحصيل التعاقدات» | P-41 `expected_contract_inflows()` | Base = expected date (agreed days, else measured); low = late placement (max observed days). Overdue → week 1 |
| **Out** | | | |
| O1 | Post-dated supplier cheques «شيكات صادرة مؤجلة» | `finance.Payment` (supplier, `cheqtype '20'`, date > `as_of`) | On the cheque date (column to verify, open question 1). low = base = high |
| O2 | Supplier payables due «مستحقات الموردين» | P-42 `supplier_outflows()` | By slice due date. **Netting:** per supplier, unallocated post-dated cheques (O1) are subtracted from that supplier's open slices, earliest due first, so a payable is never counted twice. Overdue → week 1 |
| O3 | New purchases falling due «مشتريات جديدة» | estimate | Weekly purchases (default: mean of the last 13 weeks of real-supplier 10 − 120, by category; or the "what if" `purchase_budget_weekly`) placed at + category credit days (value-weighted from P-42). Only what falls inside 13 weeks. Replaced by the P-34 budget when it exists |
| O4 | Fixed outflows «مصروفات ثابتة» | finance input | Per `FixedOutflow` schedule. low = base = high |
| O5 | Planned cheques «شيكات مخططة» | `cheques.ChequeInstalment` (plan `active`, status `pending`) | On `due_date`. Issued instalments are left out (expected in the SOFTECH mirror). This is the planner merge |
| **Memo (not in the total)** | | | |
| M1 | Internal / virtual accounts «حسابات داخلية» | O1 + O2 for `finance_internal_supplier_codes` (P-42) | Shown, never added to real outflows |
| M2 | Early-pay foregone «خصم دفع مبكر فائت» | P-42 `early_pay_by_week()` | `available_value` and `foregone_value` per week |
| M3 | Payables without terms «بدون شروط» | P-42 | Open total + count. Placed in week 1 of the **pessimistic** case only |

- **Result per week:**
  - `closing_base = opening + Σ in_base − Σ out_base` (cumulative);
  - `closing_low = opening + Σ in_low − Σ out_high`, where `out_high` = base + M3 in week 1;
  - `closing_high = opening + Σ in_high − Σ out_base`.
- **Missing inputs degrade, never guess.**
  - No opening balance → closings show "—" and only the weekly net is shown.
  - P-41 not built → I2 shows «غير متاح».
  - P-42 terms missing → payables move to M3.
- **What if:** `purchase_budget_weekly` (EGP) replaces the O3 default for that request only. Nothing is stored.

**3. Weekly snapshot.** Model `CashViewSnapshot`:
- Fields: `as_of`, `weeks` (JSON of lines and closings), `inputs_hash`, `created_at`;
- written every Sunday 06:00 by a scheduler job `cash_view_weekly_snapshot`;
- used only for forecast-vs-actual (§4).

**4. API** (`apps/finance/urls.py`, new `cash_views.py`)

| Endpoint | Method | Permission |
|---|---|---|
| `/api/finance/cash-view/?as_of=&purchase_budget_weekly=` | GET | `FINANCE` + all-branch |
| `/api/finance/cash-view/lines/<key>/?week=` | GET (drill-down rows: cheques, slices, contracts, schedules) | `FINANCE` + all-branch |
| `/api/finance/cash-view/opening-balance/` | GET / POST | GET `FINANCE`; POST `FINANCE_EDIT`; all-branch |
| `/api/finance/cash-view/fixed-outflows/` | GET / POST / PATCH | same |
| `/api/finance/cash-view/export/` | GET (xlsx) | `FINANCE_EXPORT` + all-branch |

The all-branch check uses `core/branch_scope.py` from security Batch 5 (PR 17, not on this branch yet).

**5. Screen** — new Finance hub tab `/finance/cash` «النقدية ١٣ أسبوع» (`FinanceHubPage.jsx` TABS), with inner tabs
**العرض** and **المدخلات** and `useHelpTab(tab)`.
- KPI strip:
  - lowest projected week (base and low);
  - weeks below zero;
  - input coverage: opening date, % of payables with terms, contracts with agreed days.
- Table: rows = lines grouped In / Out / Memo; 13 week columns; closing rows low / base / high (negative in orange).
  Each line label carries a source chip («SOFTECH» / «إدخال المالية» / «تقدير»).
- A cell click opens a side panel with the rows behind it (no modal).
- Simple CSS bars for weekly closing with the low–high band. No new chart dependency (none in `package.json`).
- "What if" purchase budget: one inline number field (`useNumberInputGuards`).
- **المدخلات:** opening balance and fixed outflows, inline edit.
- `DataFreshnessBar domains={['ap_reconciliation','ar_contracts','sales','purchases']}`. The `sales` refresh button
  stays; the others are engine-fed and read-only per the existing bar rule.
- `/finance/cashflow` becomes `<Navigate to="/finance/cash" replace />`. `CashFlowRetired.jsx` is no longer routed.
- The `/cheques` sidebar item stays until the owner decides (open question 6).

**6. Help** (`apps/help/content/finance.py`)
- New screen `finance.cash` (routes `['/finance/cash']`, a section per inner tab, Arabic + English, `updated`).
- **Remove** the `finance.cashflow` screen and the overview flow step with target `finance-cashflow-kpis`
  (route `/finance/cashflow`). `test_help.py` skips `<Navigate>` routes, so they would otherwise fail
  `test_no_help_for_routes_that_no_longer_exist`.
- Update `finance.cheques`: planned cheques now show in the cash view.

**Migrations:**
- `finance/0019_cash_view` (`CashOpeningBalance`, `FixedOutflow`, `CashViewSnapshot`);
- `audit/00xx` (new action choice).

## 3. Acceptance criteria

- A hand-built fixture (opening, two cheques, sliced payables, a contract with agreed days, a fixed monthly outflow)
  gives the expected base / low / high closings to the piastre (test).
- **No double counting:** a payable covered by an unallocated post-dated cheque to the same supplier is counted once
  (test). An allocated cheque's invoice is already closed and appears only as O1 (test).
- Internal accounts never change the closing figures (test).
- Missing opening → no closing figures. Missing P-42 terms → amount appears in M3 and in week 1 of `low` only (tests).
- "What if" changes only O3 and is not stored (test).
- `/finance/cashflow` redirects to `/finance/cash`. Branch-restricted user and users without `finance` → 403 on all
  endpoints. Every input change writes one `AuditLog` row with before/after (tests).
- Scheduler registers `cash_view_weekly_snapshot`; it is idempotent per Sunday (test).
- `test_help.py` passes.

**Tests**

| File | Proves |
|---|---|
| `apps/tests/test_cash_view.py` | week bucketing and banking-day shift; each line rule; netting; ranges; degradation; internal memo; what-if; snapshot idempotency |
| `apps/tests/test_cash_view_api.py` | permissions, audit, drill-down totals = cell value, export |
| `apps/tests/test_help.py` | new route has help; retired route's help removed |

## 4. Measurement

- **Forecast accuracy:** each snapshot's week-1 `closing_base` vs the next entered opening balance (the actual).
  Shown as absolute error and % per week. No baseline (new).
- **Unplanned shortfalls:** weeks whose actual is below that week's snapshot `closing_low`. Target: 0.
- **Adoption:** weekly opening balance entered (13 of 13 weeks); screen views per finance user (P-57 telemetry).

## Out of scope

- Any SOFTECH write. Stop-and-ask.
- The P-34 purchase budget (it replaces the O3 run-rate when it exists).
- Bank-feed integration; saved "what if" scenarios; daily granularity.
- An accounting module (P-44, deferred).
- Deleting the `/cheques` planner or its data.

## Open questions / owner inputs

1. **Post-dated cheque date (to verify read-only):** for `financialdoccode '20'` (شيك بنكي), is the bank due date
   `cheqdate` or `cheqcashdate`? The mirror stores only `cheqdate` as `Payment.voucher_date`.
   Also: the daily supplier sync window ends today (`date_to=today` in `_run_ap_reconciliation_sync`), so cheques
   dated after today may be missed after the backfill. Extending the voucher window forward is a read-only query
   change, but it changes supplier sync output — confirm first.
2. **Cash channels:** besides 91 (cash) and 90 (delivery), which channels are paid at the till: 30 regular, 11 staff,
   the co-pay part of 15 / 10? This ties to P-41 open question 4 (co-pay), to avoid counting cash twice.
3. **Card payments:** card sales reach the bank later. Should they be lagged, and by how many days?
4. **Week start:** Sunday (banking week) or Saturday?
5. **Opening balance:** which boxes and bank accounts count as "cash"? Finance defines it once.
6. **Cheque planner:** keep `/cheques` for ad-hoc plans (shown as O5), or retire it now?
7. **Who are the four finance users?** They need the `finance` grant with all-branch scope.

## Stop-and-ask

- Any SOFTECH write.
- Extending the supplier sync window forward (open question 1). It changes an existing sync's output.
- Linking the view to payment approval or any automatic payment choice. The view is advisory; finance decides.
