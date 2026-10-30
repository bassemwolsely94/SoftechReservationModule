# 06 · SPEC P-31 — Unordered / short delivery detector

**Status:** specification (approved for spec 2026-10-30, narrowed). **Build:** not yet authorised.
Depends on P-29 (return fast) for the return hand-off; the detector itself can ship first (see §2.6).

**Owner input** (ledger P-31, backlog revision — these override the original card)
- The order record is **the order Excel the buyer already exports**. No new step for buyers.
- Flag **unordered** lines ("return now") and **bonus missing**. Short delivery is reported, not chased.
- **No price check.** Main suppliers never exceed the agreed price.
- Unordered deliveries happen about **1–2 times a week**, from any supplier (mistakes or supplier pushes).
- Supplier orders are mostly **Excel on WhatsApp, built from our demand pivot sheet**; phone for urgent items;
  SOFTECH طلب توريد is rare.
- Pilot with the **two largest suppliers**.

## 1. Problem (measured)

- **Nothing records what we ordered from a supplier in a usable way.**
  - `invoices.PurchaseOrder` has **0 rows** (03 §Verified, Batch 3). Its matcher `apps/invoices/po.py`
    (`match_invoice_to_po`) has nothing to compare.
  - `/supply` already has an order record: `SupplyDecision(kind='purchase')`, written by
    `apps/supply/execution.py::commit_order` («تسجيل الطلب» in `OrderPanel.jsx`). It stores supplier
    (`VendorProfile`), qty, `foc_qty`, `receipt_status` (`open/received/cancelled`) and `received_qty`.
    **Nothing ever fills `received_qty`**; `receipt_status` only changes when a SupplyCase closes
    (`execution.close_open_orders_for_case`).
  - The three order Excels in use **record nothing**:

    | Export | Endpoint | Code | Supplier? | Records? |
    |---|---|---|---|---|
    | /supply order list Excel | `POST /api/supply/order-list/excel/` | `execution.export_order_excel` | name only | No |
    | Shortage list supplier PO | `GET /api/shortage/lists/<id>/export-supplier-po/<suppcode>/` | `shortage/export.py::export_supplier_po` | yes (personcode) | No |
    | Demand pivot «اولوية النواقص» | `GET /api/purchasing/export/?view=pivot` | `purchasing/views.py::_export_xlsx_pivot_v2` | **no** | No |

- **Receipts are mirrored, but not checked.** `procurement.PurchaseLine` holds every doc 10/120 line with
  `supplier_code` (= `stktransm.cust_branch_code`), `net_qty`, `raw_value` and `bonus_qty` (free units from the
  separate `pharmacydiscp=100` lines). Nobody compares it to an order.
- **Correction to the backlog card:** PurchaseLine is **not** refreshed every 30 min. The scheduler *checks*
  every 30 min (`apps/sync/tasks.py` job `procurement_refresh`) but only runs when the last success is older than
  20 h (`apps/procurement/refresh.py` `DUE_AFTER_HOURS = 20`). Same-day detection needs the on-demand
  «⟳ المشتريات» refresh or a shorter cadence (open question Q4).
- Baseline frequency: owner estimate only (1–2 unordered deliveries a week). No measured value exists.

## 2. Scope

### 2.1 One order record: `SupplyDecision(kind='purchase')` (reuse; no new order table)
- Rule 6: no parallel PO. `invoices.PurchaseOrder` stays unused (owner decides later whether to retire it, Q7).
- **Every supplier-order Excel becomes a recorded order**, through the existing `commit_order` (its
  idempotency key, item lock, all-or-nothing validation and audit `supply_purchase_ordered`):
  1. **/supply order list:** `OrderListViewSet.excel` takes the panel's `idempotency_key` and calls
     `commit_order` before building the file. A re-download with the same key replays, never records twice.
     The panel's separate «تسجيل الطلب» click is no longer needed for the Excel path; the WhatsApp-text path keeps
     it. The existing rule applies: buying more than the live need needs a reason.
  2. **Shortage list supplier PO:** a new `POST .../export-supplier-po/<suppcode>/` records one decision per
     matched item (`supplier` = `VendorProfile` by `softech_personcode`, qty = `quantity_needed`, branch = the
     list's branch, no case), then returns the same file. Key = `shortage-po:<list id>:<suppcode>:<hash of
     item+qty lines>`, so a re-download of the same list replays. Unmatched items are not recorded (they are
     already flagged «صنف غير مطابق» in the file). The GET stays for one release, then is removed from the UI.
  3. **Demand pivot:** it has no supplier and its quantities are needs, not orders. Recording it as
     `SupplyDecision` would count every need as "pending incoming" in `supply/engine/commitments.py::pending_orders`
     and suppress real needs. So it is recorded **only as a need snapshot** (2.2), never as an order.
- **Receipt fields are filled** (today they never are): `received_qty` and a new `received_bonus_qty`
  accumulate from matched PurchaseLines; `receipt_status` gains `partial` and `lapsed`
  (`lapsed` = window passed, nothing or part received). `lapsed` and `received` stop counting as pending incoming
  in `commitments.pending_orders` (today an unreceived order counts forever).

### 2.2 Need snapshot for pivot exports (small new model)
- `supply.OrderSheetSnapshot`: exported_by, exported_at, source (`pivot`), demand run id, coverage months,
  `lines` JSON `[{item_id, qty}]` for items with a positive network gap in that export.
- Written by `_export_xlsx_pivot_v2` after the file is built; a failure to record never breaks the export
  (same rule as the buy-flags columns).
- Purpose: a delivered item that was on a recent need sheet is "not on any order — check", not "unordered".

### 2.3 Receipt check (new `apps/supply/receipts.py`, deterministic, PG only)
For each PurchaseLine with `doccode='10'`, `doc_date` in the last 30 days, supplier in the pilot list:
1. **Supplier company:** compare by company group, not by account. Reuse `supply/comparison.py`
   `SUPPLIER_GROUPS` (e.g. المصرية شريف / زيتون / الحرية; أخناتون 124 / 3031 / 3030). Accounts classed as virtual,
   contract, clearing or services by `comparison._tier` are never judged (same exclusion as `buy_flags.py`).
2. **Find the order:** open or partial `SupplyDecision(kind='purchase')` for the same item and supplier group,
   created in `[doc_date − N days, doc_date]` (N = SystemSetting `receipt_check_window_days`, default 14, Q2).
   Oldest first. Allocate the received `net_qty` to them in order.
3. **Flags** (one row per PurchaseLine natural key, never per DB id, because the refresh re-pulls days):

   | Flag | Rule | Arabic label |
   |---|---|---|
   | `unordered` | no order found and the item is on no need snapshot in the window | «بدون طلب — ارجعه» |
   | `not_on_order` | no order found, but the item was on a pivot need sheet | «غير مسجّل في طلب — راجِع» |
   | `over` | received > ordered by at least one whole pack (excess only) | «زيادة عن الطلب» |
   | `bonus_missing` | expected bonus − received bonus ≥ 1 unit | «بونص ناقص» |
   | `short` | order window passed with received < ordered | «توريد ناقص» |

   - Expected bonus = `foc_qty / availability_line.supplier_qty × decided_qty`, the same scaling
     `execution.commit_order` already uses for `effective_cost`. No bonus expected when the order had no offer.
   - `short` is set on the **order**, when it turns `lapsed`; it is reported, not chased (owner).
   - No price comparison anywhere (owner).
4. **Idempotent:** `supply.ReceiptCheck` is unique on (branch_code, supplier_code, doc_number, doc_date, item_code).
   Re-runs update qty and flag; a person's decision on the row is never overwritten.
5. **When it runs:** at the end of every successful procurement refresh (`procurement/refresh.py::run_now`,
   scheduler, command and the «⟳ المشتريات» button), and nightly as a catch-up. It reads PG only.

### 2.4 Worklist: /supply tab «استلام بدون طلب» (key `receipts`)
- Rows: open flags, newest first. Columns: date, supplier (name, never a bare code), branch (via
  `useBranchLabels`), doc number, item, qty, value (`raw_value`), flag, age in days.
- Actions (server-side permission `CanOperateSupply`; audit who / when / why):
  - «مرتجع مطلوب» — return requested.
  - «مقبول» — accepted, with a required reason from a short list: طلب هاتفي / بديل متفق عليه / أخرى (text).
  - «طلب هاتفي» — the same as accepted, reason «طلب هاتفي», so phone orders stop re-flagging.
- **Outcome is automatic:** a later doc 120 PurchaseLine for the same supplier group + item marks the row
  «تم الإرجاع» with the credited value. The function `receipts.returned_since(group, item, since)` is written so P-29
  reuses it for its doc-120 auto-close.
- Grid keyboard per convention (`useGridKeyboard`: ↑↓ Space Enter). No modal for the common actions.
- Freshness bar (`DataFreshnessBar`, domain `purchases`) with its refresh button, per the module convention.

### 2.5 Alert
- One daily digest to purchasing: "N unordered lines, EGP X, oldest D days", deep link to the tab. Uses P-55
  routing (`notification_routing`) when built; until then one notification per purchasing user per day.
  No per-line notifications.

### 2.6 Link to P-29
- P-31 ships with its own «مرتجع مطلوب» → «تم الإرجاع» loop (2.4).
- When P-29 is built, «مرتجع مطلوب» rows also appear in P-29's per-supplier return list (same suppliers,
  same return entry). No second return list is built here.

### 2.7 Files
- Backend: `apps/supply/execution.py`, `apps/supply/views.py` (`OrderListViewSet.excel`), `apps/supply/models.py`
  (`SupplyDecision` fields/choices, `OrderSheetSnapshot`, `ReceiptCheck`), new `apps/supply/receipts.py`,
  `apps/supply/engine/commitments.py`, `apps/supply/urls.py`, `apps/supply/serializers.py`,
  `apps/shortage/views.py` + `export.py`, `apps/purchasing/views.py` (`_export_xlsx_pivot_v2` snapshot hook),
  `apps/procurement/refresh.py` (post-run hook), `apps/sync/tasks.py` (nightly catch-up).
- Frontend: `frontend/src/pages/SupplyPage.jsx` (tab), new `frontend/src/pages/supply/ReceiptCheckTab.jsx`,
  `frontend/src/pages/supply/OrderPanel.jsx` (key passed to Excel), `frontend/src/pages/ShortagePage.jsx`
  (POST for the supplier PO), `frontend/src/api/client.js`.
- Migration: `supply` 0012 (new fields, choices, two models). Nothing touches SOFTECH sync tables.
- Help: `apps/help/content/purchasing.py` (`/supply` page: new tab, «تسجيل الطلب» now implied by Excel, receipt
  statuses) and `apps/help/content/shortage.py` (`/shortage`: supplier PO is now recorded as an order); bump
  `updated`; `SupplyPage` already calls `useHelpTab(tab)`.

## 3. Acceptance criteria

- **Excel = order:** downloading the /supply order Excel twice with the same key creates one set of decisions
  (test). A shortage supplier-PO download records one decision per matched item; the same list again replays
  (test). A pivot export records one snapshot and **no** decisions (test).
- **Pending incoming:** a `received` or `lapsed` decision no longer counts in `commitments.pending_orders` (test);
  an `open` one still does (control).
- **Matching** (`apps/tests/test_supply_receipts.py`, new):
  - ordered 50 + 5 bonus, received 50 + 0 → `bonus_missing` 5, no `unordered` (example from the card);
  - an item on no order and no snapshot → `unordered` with value;
  - the same item on a pivot snapshot only → `not_on_order`;
  - ordered from Egy Drug Sherif, delivered under another account of the same group → matched;
  - a virtual / contract account → never flagged;
  - two receipts for one order → allocated oldest first; excess ≥ 1 pack → `over`;
  - re-running the check after a refresh re-pull → same rows, person's decision kept.
- **Outcome:** a doc 120 for the same group + item after «مرتجع مطلوب» → «تم الإرجاع» with the value (test).
- **Permissions:** a user without supply rights gets 403 on the actions (test, `test_supply_access.py`).
- Existing `test_supply_execution.py` and `test_supply_exports.py` still pass; `test_help.py` passes.

## 4. Measurement

- Unordered value received per month, per supplier (pilot two). Baseline: none measured; the first 4 weeks set it.
- % of pilot-supplier received lines that match a recorded order. This also shows whether buyers really order
  through the recorded Excels (if low, Q1 is answered "no").
- Days from flag to «مرتجع مطلوب», and to «تم الإرجاع» (doc 120 seen).
- Bonus missing: units and value per month.
- Fill rate per pilot supplier (received ÷ ordered, lapsed orders). Feeding `SupplierProfile.service_level_pct` is
  out of scope.

## Out of scope

- Any SOFTECH write. Returns are still entered in SOFTECH by staff (doc 120); this only detects and follows up.
- Price check (owner).
- Matching OCR invoices (`SupplierInvoice`) before posting; the doc 10 mirror is the receipt source. Possible later.
- SOFTECH `stockordersm/stockorders` mirroring (rarely used, owner).
- Supplier scorecard screen.

## Open questions

1. **Which Excel do buyers actually send each supplier?** If they send an edited pivot, only `not_on_order` is
   possible for those orders (no supplier, no final qty). P-57 screen telemetry plus asking the two buyers answers
   this. If the pivot dominates, a per-supplier filter on the pivot export that records an order is the next step.
2. Window N (default 14 days) and pilot suppliers: **565 Pharma Overseas** and **30 Ramco** are the largest by
   value (03 §Verified). Confirm.
3. Unit check (read-only): `SupplyDecision.decided_qty` and `PurchaseLine.net_qty` both in packs? PurchaseLine
   can be fractional for strip sales (`transqty`). To verify on 20 lines.
4. Same-day vs next-day: keep the 20 h cadence (next-day flags) or refresh purchases every 2 h in working hours
   (extra SOFTECH SELECT load)? The 2-hourly `StockLedgerLine` mirror is an alternative source only if its
   `personcode` / `suppliercode` carry the supplier on doc 10 lines — to verify (read-only).
5. Do suppliers deliver directly to branches (doc 10 at 130–170), or only to HQ 100? Affects whether branch
   matters in matching (spec matches network-wide).
6. Who owns the worklist (purchasing lead? the four HQ store specialists?).
7. Retire `invoices.PurchaseOrder` and `po.py`, or keep dormant?

## Stop-and-ask

- None of this writes SOFTECH. **But** 2.1 changes what counts as "pending incoming" in the supply engine (more
  recorded orders; `lapsed`/`received` no longer counted). That changes `/supply` recommendations. Confirm
  before build.
- Making the /supply Excel a recorded order applies the "reason needed above the need" rule to Excel downloads
  that skip it today. Confirm that buyers accept this.
