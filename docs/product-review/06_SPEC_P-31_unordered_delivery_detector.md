# 06 · SPEC P-31 — Unordered / short delivery detector

**Status:** **BUILT 2026-10-31** (owner "Build P-31"; revised spec: the order file is the demand pivot). Pilot 565 + 30 (`receipt_check_suppliers`), window 14 days (`receipt_check_window_days`).
Built as `purchasing.PivotSheetSnapshot`, `procurement.ReceiptCheck`, `procurement/receipt_check.py`, /supply «استلام بدون طلب».

**Owner input** (ledger P-31, backlog revision — these override the original card)
- The order record is **the order Excel the buyer already exports**. No new step for buyers.
- Flag **unordered** lines ("return now"). Short delivery is reported, not chased.
- **No price check.** Main suppliers never exceed the agreed price.
- Unordered deliveries happen about **1–2 times a week**, from any supplier (mistakes or supplier pushes).
- Supplier orders are mostly **Excel on WhatsApp, built from our demand pivot sheet**; phone for urgent items;
  SOFTECH طلب توريد is rare.
- Pilot with the **two largest suppliers**.

**Owner decisions 2026-10-31** (these override anything below that disagrees)
- Orders are sent mainly by Gerges Shawky; sometimes the owner, Mosa Farag, Dr Gerges, an admin or Youssef William.
- **The file sent to suppliers is the demand pivot** — `/purchasing` export `view=pivot`
  (`purchasing-pivot-<engine run date>.xlsx`, sheet «المعدلات-الشهرية») — and buyers mostly use the column
  **`Total.الفرق-مطلوب/راكد`** (positive = needed across the network). Samples checked 2026-10-31 (files of 19-10 and
  26-10): one row per item, 12,406 items, 3,599 with a positive Total gap; the item's SOFTECH supplier is on every
  row (`Items_.كود-المورد`, `Items_.المورد`).
- So the /supply order Excel and the shortage-list supplier PO are **not** the order record, and nothing in this card
  touches `SupplyDecision` or the supply engine's "pending incoming". The former stop-and-ask on that is gone.

**First run on office data, 2026-10-31 — PAUSED.** With the 19-10 and 26-10 pivots imported, 1,087 of 1,368 paid
pilot lines (19–29 Oct) were flagged: 520 `unordered` (only 10 of those items were on any sheet) and 567 `over`
(median received 2× the sheet's gap). The «unordered» items since 26-10 had a median network cover of 2.4 months and
a median Total gap of −5 on that day's sheet: buyers buy beyond one month of cover and buy covered items, so the
pivot's Total gap is not the order. Flags paused (`receipt_check_suppliers = []`); the trial rows were removed;
sheets keep being recorded on every download. Needs an owner rule for what a buyer actually orders before it resumes.

**Rule changed 2026-10-31 (owner: «Use 6 months»).** Measured first on the two pivots (19–29 Oct, 1,368 paid lines
of 565 + 30): network cover ≥ 3 months → 150 lines, ≥ 4 → 89, ≥ 6 → 39 (EGP 14,164, ~25 a week); plus 4 lines of stock
with no sales. Built: each sheet also keeps `covers` (items at ≥ 3 months, −1 = stock with no sales); the only flag is
`overstocked` «شراء رغم تغطية عالية» when the newest sheet in the 14-day window shows ≥ `receipt_check_cover_months`
(6) months or no sales. **A review list, not a return list** (reasons: عرض بونص / طلب هاتفي / توزيع على الفروع / بديل
متفق عليه). The `unordered` / `over` rules in §2.2 below are superseded. Saved pivots are re-imported to fill `covers`.

## 1. Problem (measured)

- **Nothing records what was sent to a supplier.** The pivot is a plain download (`purchasing/views.py::
  export_purchasing` → `_export_xlsx_pivot_v2`); no export is logged (0 export audit rows in 120 days, 2026-10-31).
  `invoices.PurchaseOrder` has 0 rows; `SupplyDecision(kind='purchase')` has 0 rows.
- **Receipts are mirrored, but not checked.** `procurement.PurchaseLine` holds every doc 10/120 line with
  `supplier_code` (= `stktransm.cust_branch_code`), `net_qty`, `raw_value` and `bonus_qty`. Nobody compares it to
  what was asked for.
- PurchaseLine refreshes once a day (the scheduler checks every 30 min, runs when the last success is older than
  20 h — `procurement/refresh.py` `DUE_AFTER_HOURS`), or on demand with «⟳ المشتريات». Flags are next-day unless the
  button is used.
- Baseline frequency: owner estimate only (1–2 unordered deliveries a week).

## 2. Scope

### 2.1 Record each pivot download as a need sheet (new model, no change to the file)
- `purchasing.PivotSheetSnapshot`: `exported_by`, `exported_at`, demand `run` + `calc_date`, the export's filters
  and fill horizon (as passed to `_export_xlsx_pivot_v2`), and `lines` JSON
  `[{item_code, total_gap, supplier_code}]` for items whose **`Total.الفرق-مطلوب/راكد` > 0 in that file** — the same
  value the sheet shows (the same getter writes both, so the snapshot cannot drift from the file).
- Written after the file is built; a failure to record never breaks the download (logged).
- Same run + same filters + same lines downloaded again the same day → no new row (hash of lines), so viewing the
  sheet several times does not multiply snapshots.
- **Backfill (optional, owner runs):** `manage.py import_pivot_snapshot <file.xlsx> --exported-at <date>` reads
  `itemcode`, `Items_.كود-المورد` and `Total.الفرق-مطلوب/راكد` from a saved pivot (e.g. the 19-10 / 26-10 files) so
  the detector has history from day one. Header names are matched exactly; a missing column refuses the import.

### 2.2 Receipt check (new `apps/procurement/receipt_check.py`, deterministic, PostgreSQL only)
For each `PurchaseLine` with `doccode='10'`, `doc_date` in the last 30 days, supplier in the pilot list, not a free
line (`is_foc=False`):
1. **Find the sheet:** the snapshots exported in `[doc_date − N days, doc_date]` (N = SystemSetting
   `receipt_check_window_days`, default 14) that list the item with a positive gap. The newest one is the reference.
2. **Flags** (one row per PurchaseLine natural key — the refresh re-pulls days):

   | Flag | Rule | Arabic label |
   |---|---|---|
   | `unordered` | the item is on **no** sheet in the window | «بدون طلب — ارجعه» |
   | `over` | received (sum of the item's doc-10 lines in the window, network) exceeds the sheet's Total gap by at least one whole pack | «زيادة عن الفرق المطلوب» |

   - The supplier on the sheet is the item's SOFTECH supplier, not necessarily the one ordered from, so a different
     delivering supplier is **shown, not flagged** («المورد بالشيت: …»).
   - Accounts classed virtual / contract / clearing / services (`supply/comparison.py::_tier`, as `buy_flags.py`)
     are never judged.
   - **Not built:** `bonus_missing` and `short` — the pivot carries no agreed bonus and no ordered quantity per
     supplier, so neither can be computed deterministically. They return if the order record ever carries them.
   - No price comparison anywhere (owner).
3. **Idempotent:** `procurement.ReceiptCheck` unique on (branch_code, supplier_code, doc_number, doc_date, item_code).
   Re-runs update qty and flag; a person's decision on the row is never overwritten.
4. **When it runs:** after every successful procurement refresh (`procurement/refresh.py::run_now` — scheduler,
   command and the «⟳ المشتريات» button) and nightly as a catch-up. Receipts dated before the first snapshot are
   not judged (no sheet existed).

### 2.3 Worklist: /supply tab «استلام بدون طلب» (key `receipts`)
- Rows: open flags, newest first. Columns: date, supplier (name, never a bare code), branch (via `useBranchLabels`),
  doc number, item, qty, value (`raw_value`), flag, the sheet's gap and its supplier, age in days.
- Actions (server-side `CanOperateSupply`; audit who / when / why), no modal:
  - «مرتجع مطلوب» — return requested.
  - «مقبول» — accepted, with a reason from a short list: طلب هاتفي / بديل متفق عليه / أخرى (text).
- **Outcome is automatic:** a later doc 120 for the same supplier + item marks the row «تم الإرجاع» with the
  credited value — the same each-line-once rule as P-29's `return_calendar.reconcile_returns`.
- Grid keyboard (`useGridKeyboard`: ↑↓ Space Enter); freshness bar (`purchases`) with its refresh button.

### 2.4 Alert
- One daily digest to the `purchasing` role: "N unordered lines, EGP X, oldest D days", deep link to the tab;
  new notification type (label-only migration) so P-55 routing applies. No per-line notifications.

### 2.5 Files
- Backend: `apps/purchasing/views.py` (snapshot hook in the pivot export), `apps/purchasing/models.py`
  (`PivotSheetSnapshot`), new `apps/procurement/receipt_check.py`, `apps/procurement/models.py` (`ReceiptCheck`),
  `apps/procurement/refresh.py` (post-run hook), `apps/supply/views.py` + `urls.py` (worklist + actions),
  new `apps/purchasing/management/commands/import_pivot_snapshot.py`, `apps/sync/tasks.py` (catch-up + digest),
  `apps/notifications/models.py` (type).
- Frontend: `frontend/src/pages/SupplyPage.jsx` (tab), new `frontend/src/pages/supply/ReceiptCheckTab.jsx`,
  `frontend/src/api/client.js`.
- Migrations: `purchasing`, `procurement`, `notifications`. Nothing touches SOFTECH or the supply engine.
- Help: `apps/help/content/purchasing.py` (`/supply` new tab; `/purchasing` "each pivot download is kept as the
  sent need sheet"); bump `updated`.

## 3. Acceptance criteria (`apps/tests/test_receipt_check.py`, new)

- A pivot download writes one snapshot holding exactly the positive `Total.الفرق-مطلوب/راكد` rows of the file;
  the same download again the same day writes none; a recording failure still returns the file.
- `import_pivot_snapshot` on a sample pivot gives the same lines as the live export's snapshot logic; a file
  without the Total column is refused.
- An item on no sheet in the window → `unordered` with value; on a sheet → no flag.
- Received above the sheet's gap by ≥ 1 pack → `over`; below or equal → nothing.
- A virtual / contract account → never flagged. A free (FOC) line → never judged.
- A receipt before the first snapshot → not judged.
- Re-running after a refresh re-pull → same rows; a person's decision kept.
- A doc 120 after «مرتجع مطلوب» → «تم الإرجاع» with the value; that line is used once.
- A user without supply rights gets 403 on the actions; `test_help.py` passes.

## 4. Measurement

- Unordered value received per month, per pilot supplier. Baseline: none measured; the first 4 weeks set it.
- Share of pilot-supplier received lines that were on a sheet — also shows whether orders really come from the pivot.
- Days from flag to «مرتجع مطلوب», and to «تم الإرجاع» (doc 120 seen).

## Out of scope

- Any SOFTECH write. Returns are still entered in SOFTECH (doc 120); this only detects and follows up.
- Price check (owner). Bonus and short-delivery checks (no deterministic source — see 2.2).
- Recording the /supply order Excel or the shortage-list supplier PO as orders; changing `SupplyDecision` or the
  supply engine's pending-incoming rule.
- `invoices.PurchaseOrder` (stays unused).

## Open questions

1. Window N: default 14 days (pivots are about weekly — 19-10, 26-10). Confirm.
2. Pilot suppliers: **565 Pharma Overseas** and **30 Ramco** proposed (largest by value). Confirm.
3. Do suppliers deliver directly to branches (doc 10 at 130–170), or only to HQ 100? The spec matches network-wide.
4. Who owns the worklist (purchasing lead? the HQ store specialists?).
5. Should the two saved pivots (19-10, 26-10) be imported as history?

## Stop-and-ask

- None. No SOFTECH write and no change to existing recommendations. Build still needs the owner's go-ahead.
