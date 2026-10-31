# 06 · SPEC P-27 — Dead-stock recovery: move what sells elsewhere, return or stop what sells nowhere

**Status:** specification. **Build: not yet authorised.** Wave 2 (stock and availability).
Two parts:
- **Part A** — read-only dead-stock tab on `/cash-optimization` (doc 22 step 2) with three lanes and an Excel export.
  It has no dependency and can be built alone.
- **Part B** — the «يُباع بفرع آخر» lane inside «التوزيعة». It **depends on doc 30 phase B** (plan ledger + wave 0),
  which is not built, and it only switches on after the owner reviews the first Part A list.

**Owner input** (ledger row P-27, backlog P-27 "Revision after owner input", doc 22 owner decisions 2026-09-15 —
these override the original card)
- Dead stock "mostly just sits". Moving it to where it sells is the fix.
- The tab replaces the occasional WhatsApp posts and HQ pull-backs with **one ranked list**.
- The doc-30 value threshold stays: **nothing under 100 EGP per move**.
- Smallest version first: read-only tab with three lanes (move / return / stop) and an Excel export. Moves are added to
  «التوزيعة» **only after the owner reviews the first list**.
- Doc 22 (owner-locked 2026-09-15):
  - Dead = no sales in **6 months** and not a `strategic_hold`.
  - Location is the master signal: HQ-only → return; branch-only → move; both → obsolete (موقوف).
  - Returns are **advisory**. Nothing drafts a return document.
  - Only big distributors, manufacturers and warehouses take returns, so return suggestions are gated on the supplier
    class.
- Store 110 is excluded everywhere (P-26 decision 2026-10-31).

## 1. Problem (measured)

- **Slow and dead branch stock** (engine run #104, 2026-10-27, stock > 0, at current `Item.cost_price`;
  `05_PROPOSAL_BACKLOG.md` Batch 2 "Measured picture"):

  | Bucket | Value (cost) |
  |---|---|
  | Branch stock with no local sale in 6+ months (5 branches) | **1.87M** |
  | … of which the item sells at other branches | **1.43M** (≈ **713k** fits directly into another branch's 2-month gap) |
  | … of which the item sells nowhere in the network | **437k** |
  | `strategic_hold` items | **0 set** |

  These figures did **not** apply the "stock received ≥ 6 months ago" rule. They are re-measured with this spec's
  rules at build time.
- Earlier network picture (doc 22 §2, run #67, 2026-09-09): dead stock ≈ 1.47M (3,558 items). By location: HQ-only
  116k, branch-only 1,037k, both 315k.
- `ItemDemandMetrics.last_sale_date` is null for 7,947 stocked item × branch rows (2.58M). That means "no sale in the
  engine's window", not proven "never" (`03_DATA_OPPORTUNITY_MAP.md`, Batch 2).
- In «التوزيعة», half of branch-sourced moves are under 100 EGP (2,586 of 5,226 suggestions; doc 30 §1).
- The old TransferEngine produced 527k unused recommendations (backlog card).
- **Nobody measures what happens to moved stock.** No baseline exists for sell-through after a move.

### Code facts that shape the build (read in the repo)

- `/cash-optimization` (`frontend/src/pages/CashOptimizationPage.jsx`) has one working tab, «📈 ذروة الطلب». The «🧊 مخزون
  راكد» and «📦 فائض» tabs are disabled «(قريبًا)» buttons (lines 151–156). It already calls `useHelpTab(tab)`. The
  backend is `apps/purchasing/spike_views.py` (read = `matrix_permission('analytics')`, review =
  `matrix_permission('purchasing', post=('edit','approve'))`).
- `catalog.Item.strategic_hold` exists (`apps/catalog/models.py:261`, indexed). **No endpoint or screen sets it.**
  `Item.requires_fridge` and `Item.no_more_use` (SOFTECH `itemnomoreuse`) also exist.
- `purchasing.ItemDemandMetrics` (one row per item × branch per engine run) carries `current_stock`, `monthly_avg`,
  `qty_365d`, `gap`, `in_transit_qty`, `abc_class` and `last_sale_date`.
  - `last_sale_date` = `MAX(doc_date)` of doccode 115 inside the 365-day window (`purchasing/queries.py`
    `PG_AGGREGATE_SQL`). Rows whose 365-day net qty is ≤ 0 are dropped by `HAVING SUM(net_qty) > 0`, so they read
    as "no sale".
  - The engine runs Sunday + Wednesday at 01:00 (`sync/tasks.py` job `demand_engine_scheduled`, gated by
    `DEMAND_ENGINE_SCHEDULE_ENABLED`).
- **Stock age already has a function.** `apps/batches/expiry_audit.py` has `ARRIVAL_DOCCODES = ('10','25','30','50')`
  (purchase, transfer-in, sales return, surplus) and `_fifo_oldest_date(arrivals, current_qty)`: the arrival date of
  the oldest unit still on hand. Today its arrivals come from a live SOFTECH read (`_stock_in_arrivals`), but the
  fetcher is injectable (`arrivals_fetcher`).
- `stock_audit.StockLedgerLine` is a PostgreSQL mirror of every branch's stock lines (`branchcode`, `doccode`,
  `docdate`, `itemcode`, `transqty`, `newqty`). The window is rolling 365 days (`STOCK_AUDIT_WINDOW_DAYS`). It has the
  freshness domain `stock_audit` (cadence 120 min). **So stock age can be computed in PostgreSQL with no new SOFTECH
  read.** An arrival older than 365 days is not visible.
- `distribution._item_ages` reads SOFTECH `stkbal MIN(opendate)` live. That is the item's **first-stocked date
  network-wide**, not how long this branch's units have sat. It is not used for the age rule here.
- **Why «التوزيعة» cannot see locally dead stock today** (`apps/purchasing/distribution.py`):
  - `over_piled` needs a SOFTECH ceiling at the source (`_branch_ceilings`: live `stkbal maxnowqty > 0`). Items that
    stopped selling at a branch have no ceiling there.
  - The ESTABLISHED guard (`if established and not surplus: continue`) skips old, broadly selling items unless they
    are over a ceiling. A locally dead but network-established item is therefore skipped.
- ISR drafts: `isr_writer.create_distribution_proposals` → `_persist_proposal`. The DB constraint
  `isrpush_one_live_draft_per_route` allows **one live general draft per (kind, source, destination)**; a new draft
  supersedes the old one (`isr_guards.check_route_free` / `retire`). **A separate dead-stock generation on the same
  route would cancel the «التوزيعة» draft.** The lane must live inside the same plan, which is why Part B waits for
  doc 30 phase B.
- Doc 30 phase B is **not built**: no `DistributionPlan` or `PlannedMove` model exists in `apps/`.
- Move history: `distribution._seeded_history()` reads `IsrPush.lines_snapshot` per (item, destination) from
  approved/pushed توزيعة legs. `distribution._allocate(excess, targets, room)` splits whole packs over targets.
- Near-expiry moves already exist in `apps/batches/rebalance.py` (P-28 area): short-dated batches from
  `StockExpiryBalance` (live stores, P-26 roles), horizon `EXPIRY_REBALANCE_HORIZON_DAYS` (180), creating **draft
  transfers via the /transfers/ API**, with a flag when an open transfer already covers the line.
- Supplier class: `apps/supply/comparison.py` maps SOFTECH classes `60` → distributor, `70` → manufacturer, `50`/`20` →
  warehouse, via `SupplierProfile.classif_code`. Doc 22 §3.4 names the same returning classes (20/60, 70, 50).
  `procurement.PurchaseLine` holds every doc 10/120 line (`supplier_code`, `item_code`, `branch_code`, `doc_date`).
- P-29 is built: `apps/batches/return_window.window_for(expiry_date, today, …)` and `procurement.SupplierReturnPolicy`
  (565, 260).
- Three other "dead stock" numbers exist, each with its own rule: `insights.rules.rule_dead_stock` (`ItemStock`
  `monthly_qty ≤ 0`), the analytics inventory dashboard (`monthly_avg ≤ 0`, `analytics/views.py:1504`) and the
  advanced engine flag `dead_stock`. This spec does not change them (see Out of scope).
- Doc 22 §3.2 asks for a "variant-cannibalized" cause hint by reusing a "phantom name-prefix matcher". **No such
  matcher exists in `apps/purchasing/phantom.py`.** That hint is not in Part A (open question 9).
- `core/branch_scope.py` is present on this branch.

## 2. Scope

### 2.1 One classifier (new `apps/purchasing/dead_stock.py`, pure, PostgreSQL only)

Input: the latest successful `DemandCalculationRun`. One function, `classify(rows, today, settings) → lines`, with no
DB access, so tests use fixtures. A thin loader feeds it.

**Per (item, branch) row**, from the run's `ItemDemandMetrics`:

1. **Candidate:** `current_stock > 0`, the branch is active (`Branch.is_active`), `Item.is_stockable`, and the
   item is not `strategic_hold`.
2. **No local sale ≥ N months:** `last_sale_date` is null or older than `today − N months`.
   N = SystemSetting `dead_stock_months`, default **6** (doc 22 §4.3).
3. **Stock received ≥ N months ago:** the FIFO oldest-unit date from `expiry_audit._fifo_oldest_date`, fed by a new
   PG fetcher over `StockLedgerLine` (doccodes `ARRIVAL_DOCCODES`, that branch, that item, 365-day window).
   - Oldest unit arrived within N months → **not dead** (it may be a fresh trial seed or a recent transfer in).
   - No arrival in the window → age shown as «أقدم من سنة» and treated as old.
   - The ledger is per branch (`branchcode`). Whether `newqty` is per store or per branch is still unverified
     (data map, Batch 3); the FIFO only uses `transqty` of arrivals and the engine's `current_stock`.
4. **Network rate** = sum of `monthly_avg` at the *other* active branches. Value = `current_stock × Item.cost_price`
   (same basis as the baselines).

**Location** (doc 22 §4.2), per item: dead only at HQ `100` · dead only at branches · dead at both.

**Lanes** (one per line):

| Lane | Arabic label | Rule | Suggested action |
|---|---|---|---|
| `move` | «يُباع بفرع آخر» | branch line is dead, network rate > 0 | move to the branch that sells it |
| `return` | «مرتجع للمورد» | network rate = 0, and the item's latest supplier is a returning class | HQ return list (advisory) |
| `stop` | «إيقاف (موقوف)» | network rate = 0 and not returnable, or dead at both HQ and branches with `no_more_use` already set | suggest موقوف |

- **Latest supplier** = supplier of the item's most recent doc 10 `PurchaseLine` (any branch). Returning class =
  `SupplierProfile.classif_code` in SystemSetting `dead_stock_return_classes`, default `['20','60','70','50']`
  (doc 22 §3.4). No purchase line → lane `stop`, supplier «غير معروف».
- **Cause hint** (doc 22 §3.2, shown as a chip, never acted on):
  - `supplier_push` «دفع مورد / شراء مركزي» — dead only at HQ, and bought but no sale in the window;
  - `demand_died` «توقف الطلب» — `qty_365d > 0` at this branch but no sale in N months;
  - `obsolete` «متقادم» — dead at both, or `no_more_use`.
- **Return window chip** (lane `return`): where the line has batches in `StockExpiryBalance` and the supplier has a
  `SupplierReturnPolicy`, show `return_window.window_for` state. No new window rule.

**Move lane: target and quantity**

- **Targets:** other active branches with `monthly_avg > 0` for the item. HQ is never a target. Targets that sent this
  item out in the last N months are skipped ("no move-back within 6 months"): a `branch_to_hq` `IsrPush` leg from that
  branch with the item (`lines_snapshot`), or a doc 125 issue from that branch in `StockLedgerLine`.
- **Room at a target** = `max(0, gap)` from the same engine run (gap already nets stock and in-transit). Part B
  replaces this with the plan's live inputs (doc 30 §2.7). See open question 2 on the gap horizon.
- **Order:** the target with the largest room first, through `distribution._allocate` (whole packs, ≥ 1 pack).
  At most `distribution.MAX_TARGETS` (4) targets.
- **Short-dated lots first** (backlog card): if the source holds live-store batches expiring within
  `EXPIRY_REBALANCE_HORIZON_DAYS` (180), the line is ranked first and its targets are ordered by `monthly_avg`
  (fastest seller) instead of room.
- **Value threshold:** a move line under SystemSetting `dead_stock_min_move_value` (default **100 EGP**, doc 30 §2.4) is
  not proposed. It stays visible as «أقل من حد القيمة».
- **Cold chain:** `requires_fridge` items are shown but never proposed for a move during the pilot (backlog risk).
- **No double move with P-28:** a line whose item + source already has an open transfer draft from
  `batches/rebalance.py` (reuse its `_open_transfers` check, statuses `OPEN_TRANSFER`) is marked «متعارض» with that transfer's number.

### 2.2 Snapshot per engine run (new models, migration `purchasing`)

The engine's metrics are replaced each run, so the list and its history are stored.

- `purchasing.DeadStockSnapshot`: `run` (FK `DemandCalculationRun`), `computed_at`, `settings_used` (JSON),
  `totals` (JSON per lane × branch × location: count, qty, value), `status`.
- `purchasing.DeadStockLine`: `snapshot` FK, `item` FK, `branch_code`, `lane`, `location`, `cause`, `qty`, `value`,
  `last_sale_date`, `oldest_arrival_date`, `age_note`, `network_rate`, `targets` (JSON `[{branch, qty, room, rate}]`),
  `soonest_expiry`, `supplier_code`, `supplier_class`, `window_state`, `flags` (JSON: `fridge`, `below_threshold`,
  `conflict`).
- Unique on (snapshot, item, branch_code). Re-computing a run replaces that run's lines in one transaction.
- **When it runs:** after each successful engine run (a post-run hook next to the existing ones), plus a «⟳ إعادة
  الحساب» button on the tab (background job with `ProgressBar`).
- Retention follows P-56: snapshots of runs that `sync/maintenance.py` no longer keeps are deleted with them (FK
  cascade). `totals` of the 1st-of-month snapshot are kept for the KPI (same rule as P-56 "1/month").

### 2.3 Review decisions (new model, migration `purchasing`)

- `purchasing.DeadStockDecision`: `item`, `branch_code` (blank = all branches), `decision` (`exclude` «استبعاد» |
  `keep_local` «يبقى بالفرع»), `reason` (short list: مريض معروف / عرض قادم / خطأ رصيد / أخرى + text), `until` (date,
  default today + N months), `decided_by`, `decided_at`.
- An open decision hides the line from the default view (a filter shows them). It never deletes a line.
- **Strategic hold** is set on `Item.strategic_hold` from the tab (no migration; the field exists).
- Rights, checked server-side: read = `matrix_permission('analytics')` (as the spike tab); decisions and strategic
  hold = `matrix_permission('purchasing', post=('edit','approve'))`. Every change writes `AuditLog.log` with
  before/after.

### 2.4 API (`apps/purchasing/dead_stock_views.py`, `apps/purchasing/urls.py`)

| Method | Path | Does |
|---|---|---|
| GET | `/api/purchasing/dead-stock/summary/` | totals of the latest snapshot per lane, location and branch; run date |
| GET | `/api/purchasing/dead-stock/lines/` | lines; filters lane, branch, location, cause, flags, `q` (`catalog/wildcard.py`); `format=xlsx` |
| POST | `/api/purchasing/dead-stock/recompute/` | start the background recompute; returns a job id for the `ProgressBar` |
| POST | `/api/purchasing/dead-stock/decisions/` | create / close a decision (audited) |
| POST | `/api/purchasing/dead-stock/strategic-hold/` | set / clear `Item.strategic_hold` (audited) |

- Branch scope: a user whose role is branch-bound sees only own-branch lines, through `core/branch_scope.py`.
- Excel: one sheet per lane plus a summary. Branches by name (`BL` / branch labels), never a bare code.

### 2.5 Screen: `/cash-optimization` tab «🧊 مخزون راكد» (key `dead`)

1. **Enable the tab.** «📦 فائض» stays disabled (doc 22 step 3, not this card).
2. **Header:** engine run date and snapshot time; `DataFreshnessBar domains={['stock','sales','stock_audit','purchases']}`;
   «⟳ إعادة الحساب» with `ProgressBar`.
3. **Lane chips** with count and value: «يُباع بفرع آخر» · «مرتجع للمورد» · «إيقاف». Location chips (الرئيسي فقط / فروع
   فقط / الاثنين). Branch filter via `useBranchLabels`. Search.
4. **Grid** (`useGridKeyboard`: ↑↓, Space tick, Ctrl+A, Enter = open targets row inline). Columns:
   - item, branch, qty, value, last sale, oldest arrival (age in months), network rate;
   - lane, cause chip, flags (fridge / under 100 / متعارض);
   - targets (branch name + qty + rate) for `move`; supplier + class + window chip for `return`.
5. **Actions** on ticked rows, inline (no modal): «استبعاد» (+ reason select), «احتفاظ استراتيجي», «⬇️ تصدير Excel».
6. Part A has **no "create transfer" button.** Moves happen only through Part B.

### 2.6 Part B — the «يُباع بفرع آخر» lane in «التوزيعة» (after doc 30 phase B)

Built only when doc 30 phase B (`DistributionPlan`, `PlannedMove`, wave 0) exists and the owner has reviewed the first
Part A list.

- The plan builder reads the latest `DeadStockSnapshot` `move` lines with no open decision and adds them as
  `PlannedMove` rows with reason tag `locally_dead`. An item already moved for another reason to the same destination
  appears once (doc 30 §2.1, reasons kept as tags).
- **Wave 0 applies first** (doc 30 §2.2): open SOFTECH ISRs, live drafts, in-transit, WhatsApp/fulfilment legs, and
  open rebalance transfers are subtracted. Covered moves go to «متعارض».
- **Wave position:** proposed after wave 2 (`over_piled`), since both are branch-sourced cash release. Owner decides
  (open question 3).
- Doc 30 thresholds apply: 100 EGP per line, 1,000 EGP per route document; a route under 1,000 waits for the next run.
- Routes reuse the existing legs: branch → HQ (`branch_to_hq`) and HQ → branch (`hq_to_branch`), consolidated per
  doc 30 §2.5 and the leg-order rule (HQ → branch only after its branch → HQ leg is pushed).
- Switch: SystemSetting `dead_stock_in_distribution`, default **False**. Off = the lane is not in the plan.
- **Outcome per move:** the `PlannedMove` records receipt at the destination (doc 25 in `StockLedgerLine`) and units
  sold there within 90 days (doccode 115 `SalesTransactionLine` after the receipt date). Shown on the dead-stock tab
  as «تم النقل — بيع خلال 90 يوم: X%».
- Approve and push stay the existing /supply ISR flow (`isr_writer.push_isr_record`, `writer_allowed` gate). **Pushing
  is a SOFTECH write → stop-and-ask.**

### 2.7 Help

- `apps/help/content/purchasing.py`, screen `purchasing.cash` (`/cash-optimization`): Arabic + English.
  - Summary: add the dead-stock tab.
  - New tab entry `dead`: the dead rule (6 months no local sale **and** oldest unit received 6+ months ago), the three
    lanes, location, cause chips, the 100 EGP threshold, fridge exclusion, «متعارض», strategic hold and «استبعاد»,
    "the ledger shows one year, so older stock reads «أقدم من سنة»".
  - Tour: drop "«🧊 مخزون راكد» … (قريبًا)"; add targets for the lane chips, grid and actions.
  - Bump `updated`; `change_note`.
- Part B: `purchasing.supply` tab `dist` gains the `locally_dead` reason and its wave; bump `updated`.
- `CashOptimizationPage` already calls `useHelpTab(tab)`.

### 2.8 Files

- Backend: new `apps/purchasing/dead_stock.py`, new `apps/purchasing/dead_stock_views.py`,
  `apps/purchasing/models.py` (3 models), `apps/purchasing/urls.py`, `apps/batches/expiry_audit.py` (PG arrivals
  fetcher beside `_stock_in_arrivals`, same output shape), engine post-run hook, `apps/purchasing/supply_exports.py`
  (Excel).
- Frontend: `frontend/src/pages/CashOptimizationPage.jsx` (enable tab), new
  `frontend/src/pages/cash/DeadStockTab.jsx`, `frontend/src/api/client.js`.
- Migrations: `purchasing` only. No catalog migration. Nothing writes to SOFTECH in Part A.
- Part B: `apps/purchasing/distribution.py` / the doc 30 plan builder, `apps/help/content/purchasing.py`.

## 3. Acceptance criteria

- One function decides dead / lane / targets. The tab, the Excel and Part B all read its output.
- On the office DB (read-only check after deploy), the move / return / stop totals are shown next to the backlog
  baselines (1.43M / 437k of 1.87M). Differences are explained: the stock-age rule, the 100 EGP threshold,
  fridge items, `strategic_hold`.
- A buyer can filter, tick, exclude with a reason and set strategic hold without a modal. The next snapshot hides
  the excluded line; the audit row exists.
- No SOFTECH read or write in Part A (code review: no `config.sybase` import in the new modules, no writer import, no
  `writer_allowed` call).
- Help updated; `test_help.py` passes; frontend build passes.

### Tests (new `apps/tests/test_dead_stock.py`)

| Test | Proves |
|---|---|
| dead rule | no sale 7 months + oldest arrival 8 months → dead; sale 5 months ago → not; arrival 2 months ago → not |
| null last sale | `last_sale_date` null + old arrival → dead; no arrival in window → «أقدم من سنة» |
| FIFO age | small recent top-up on an old batch → oldest date = the old arrival (`_fifo_oldest_date`) |
| lanes | network rate > 0 → `move`; 0 + class 60 supplier → `return`; 0 + class 80 → `stop`; no purchase → `stop` |
| location | HQ-only / branch-only / both on fixtures |
| exclusions | `strategic_hold` never listed; inactive branch and store 110 never listed |
| targets | largest room first; whole packs; ≤ 4 targets; HQ never a target |
| short-dated | a lot expiring in 60 days ranks first; targets by rate |
| move-back | a branch that sent the item out 3 months ago is not a target |
| threshold | a 60 EGP move → not proposed, flagged «أقل من حد القيمة» |
| fridge | `requires_fridge` → shown, no targets |
| conflict | an open rebalance transfer for item + source → «متعارض» |
| snapshot | re-compute of the same run replaces its lines; unique key holds |
| decisions | exclude hides the line until `until`; audit row; 403 without purchasing edit/approve |
| branch scope | a branch-bound user sees only own-branch lines |
| no SOFTECH | the classifier and loader run with SOFTECH unreachable |

Existing tests to keep green: `test_spike_scoring.py`, `test_distribution_ceilings.py`, `test_purchase_expiry_audit.py`
(the PG fetcher must not change `stock_age_days`), `test_expiry_rebalance.py`, `test_gap_permissions.py`, `test_help.py`.

## 4. Measurement

- **Branch-dead value** per branch per month, from 1st-of-month `DeadStockSnapshot.totals`. Baseline 1.87M (backlog;
  re-measured with the age rule at build).
- **Locally-dead-sells-elsewhere value.** Baseline 1.43M.
- Part B: **moved value**, and **sold-within-90-days-of-receipt rate** (units sold at the destination ÷ units
  received). No baseline; it starts with the pilot. Count only lines actually received and later sold (backlog
  benefit rule).
- **Avoided-purchase estimate:** moved units later sold at the destination × cost. This is an estimate, labelled so.
- Pilot (backlog): 2 source branches × 8 weeks, compared with the other 3 branches.

## Out of scope

- Any SOFTECH write: return documents (doc 120), موقوف (`itemnomoreuse`), transfers, adjustments. Part A only lists.
- Overstock tab (doc 22 step 3) and any change to the spike tab.
- Any change to المطلوب / gap. Dead stock is already not reordered (doc 22 §3).
- Markdown or price change (pricing: stop-and-ask, separate card).
- Changing the other dead-stock numbers (insights rule, analytics dashboard, advanced engine flag). They keep their own
  definitions until the owner asks to align them.
- Annotation columns on the demand pivot export (doc 22 §6). That file goes to suppliers (P-31), so adding columns needs
  an owner decision (open question 10).
- The "variant-cannibalized" cause hint (no verified matcher).
- Near-expiry decisions (return / move / corner / loss). That is P-28; this card only avoids double moves.

## Open questions / owner inputs

1. **Stock-age source.** This spec uses FIFO over the 365-day ledger mirror. Alternative: SOFTECH `stkbal.opendate`
   per branch. Its per-branch meaning (first stocked there? row created?) is unverified; a 20-row read-only sample
   would settle it.
2. **Room at the target.** The 713k baseline used a **2-month gap**; the engine's own gap uses its default horizon
   (1 month in the global engine). Use the engine gap, a 2-month gap, or the SOFTECH ceiling room (as `over_piled`)?
3. **Wave position** of the lane in doc 30 (proposed: right after wave 2 `over_piled`).
4. **Returning classes:** 20 / 60 / 70 / 50 (doc 22 §3.4). Confirm. Is "latest doc 10 supplier of the item" the right
   source when several suppliers sold it?
5. **Pilot:** which 2 source branches?
6. **List owner:** HQ purchasing / replenishment specialists (`purchasing` role, as P-29), or the HQ store specialists?
7. **Fridge items:** excluded from moves in the pilot. Also from the return list?
8. **Stop lane:** who sets موقوف, and how? By hand in SOFTECH, or through the existing shortage writer (a SOFTECH
   write, stop-and-ask)?
9. **Variant-cannibalized hint:** build a name-family matcher later, or drop the hint?
10. **Pivot annotation columns** (doc 22 §6): wanted, given the pivot is the file sent to suppliers?
11. **Short-dated dead lots:** they also qualify for P-28 / `rebalance.py`. Which card owns lots within 180 days of
    expiry? This spec ranks them first and marks conflicts, but does not create transfers for them.
12. **Branch visibility:** should branch pharmacists see their own branch's dead stock on this tab?
13. Rows dropped by `HAVING SUM(net_qty) > 0` (sales cancelled by returns) read as "no sale". Acceptable?
14. Value basis = current `Item.cost_price`, as in the baselines. Confirm.

## Stop-and-ask

- **Part B before doc 30 phase B.** The one-live-draft-per-route constraint means a separate dead-stock draft would
  cancel the «التوزيعة» draft on that route.
- **Switching on `dead_stock_in_distribution`** — only after the owner reviews the first list.
- **Approving or pushing any ISR** that carries lane moves: a SOFTECH write through the existing writer. It must stay
  idempotent (doc 30 push guard, `isr_guards.check_push`).
- Any return document, موقوف write, transfer posting or price change.
- Build still needs the owner's go-ahead.
