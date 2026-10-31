# 06 · SPEC P-34 — Velocity-tiered cover under a cash budget

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
Wave 2, **report first**. This spec builds a **read-only** report and an advisory "within budget" ranking. It changes
no ISR quantity and writes nothing to SOFTECH. Applying tiers to the ISR rule or to the coverage writer is a later,
separate step with its own SOFTECH-write confirmation (§ Stop-and-ask).

**Owner input** (ledger row P-34; overrides the backlog card)
- Approved as revised.
- **Tier values and the slow-item "order on demand" rule are confirmed at spec time.** This spec therefore
  *proposes* them with their basis (§2.1). None is decided until the owner confirms (open questions 1–3).
- **Chronic-patient items are never on-demand.**
- **Any coverage-writer change is a separate SOFTECH-write confirmation.**
- Dependencies named in the ledger: P-30 (measure), P-27 / P-29 / P-31 (cash release).
- P-32 decision: the advanced engine's Phase E "ROI priority under a cash budget" becomes the basis of P-34.
- P-40 (built): "the P-34 purchase budget replaces the O3 run-rate when it exists". Weeks start Saturday.

## 1. Problem (measured)

- The business is cash-constrained (owner). The owner's stated root cause: "cash-flow deficit → 0.8 months →
  frequent stockouts".
- **Cover is uniform.** SOFTECH's own ISR rule, decoded read-only 2026-10-24: `itemqty = ceil(rate × 0.8 − stock)`
  for every item (`apps/purchasing/isr_softech.py`, `SOFTECH_ORDER_MONTHS = 0.8`).
- **Measured cash vs availability** (backlog, batch 3; branches 130–170, engine run #104, current cost):

| Velocity (sales / month) | Stock held | Monthly cost of sales | Cover | Item × branch at zero | Est. lost margin / 30 d |
|---|---|---|---|---|---|
| Fast ≥ 4 | 2.56M | 4.48M | ≈ 0.57 mo | 392 | 69k (85% of the estimate) |
| Medium 1–4 | 1.87M | 1.98M | ≈ 0.94 mo | 1,874 | 11k |
| Slow < 1 | **2.39M** | 1.45M | ≈ 1.6 mo | 8,922 | not estimated |

- Slow movers hold as much cash as fast movers. Fast movers carry most of the measurable lost margin.
- One pack for every zero-stock slow item would cost ≈ 2.38M. Adding 0.4 months to fast and medium items would cost
  ≈ 2.58M. Neither is affordable. **The cash must be allocated, not spread.**
- The lost-margin figures are engine estimates (`lost_sales_engine.py`), not measured stockouts. P-30 gives the
  measured figure; it is not built yet.

**Code facts that shape the build (read in the repo)**
- **Two order rules exist today.**
  - SOFTECH-rule ISR (`isr_softech.py`): target = rate × «حد الطلب» (0.8) or the stored maximum; need =
    `softech_need(target, stock, transit)` (whole packs, under 0.16 pack → 0). It reads rate, maximum and stock
    **live** from server 100 (`_read_softech`). `plan_lines(...)` is a pure function and can be reused on PG inputs.
  - Engine gap (`engine.py` `calc_gap`): `max(safety_stock, monthly_avg × coverage_months) − stock`. Coverage is
    per **ABC** class (`EngineConfig.coverage_months_a/b/c`, default 1.0; `_apply_coverage`, MODULE 10.5).
- **ABC is value, not velocity.** `_classify_abc` is a network Pareto on monthly value (A < 70%, B < 90%). An item
  can be A on the network and slow at one branch. The measured table above uses velocity per item × branch.
- **Lowering engine coverage below 1 month is a no-op.** The safety floor stays 1-month calibrated, so
  coverage 0.8 changed 23 of 39,963 rows (memory: gap horizon note, 2026-09-28). The pivot export's
  `scale_demand_gap` (`views.py:456`) scales the whole target below 1 month for this reason. Tier targets below
  1 month must scale the whole target, not the throughput term.
- **Phase E already exists** (`advanced_engine.py`):
  - `compute_row` gives `policy_demand` (Croston or trend/seasonal), `rec_order_qty`, `order_now`, `urgency`,
    `roi`, `priority_score = roi × (0.5 + 0.5 × urgency) × confidence × ABC weight` (lines 307–319).
  - `run_advanced_ranked` sorts buy candidates by `priority_score` and funds them greedily under `cash_budget`;
    a line that does not fit is skipped and a cheaper lower line may still fit (lines 469–510).
  - It is **export-only**: `GET /api/purchasing/advanced-export/?budget=` (`views.advanced_export`), with a budget
    field in the `/purchasing` export menu (`PurchasingDashboard.jsx` `advBudget`).
  - **Limits for cash use:** it is `float`, not `Decimal`. `rec_order_value = rec_qty × pack_price`, i.e. **sale
    price, not cost**, so the budget is consumed at sale value. Margin falls back to 15% (`default_margin_pct`) when
    cost is missing.
  - It already flags `order_on_demand` (`policy_demand < min_monthly_rate = 0.02`) and `dead_stock` (no sale in
    `dead_no_sale_months = 6`). `item_coverage_floor` (per-item floor, "e.g. a life-critical chronic med") exists
    and is empty.
- **Inputs available in PostgreSQL** (no SOFTECH read needed): `ItemDemandMetrics` per (item, branch, run):
  `monthly_avg`, `current_stock`, `in_transit_qty`, `safety_stock`, `abc_class`, `last_sale_date`, `pack_price`;
  `Item.cost_price`; `SalesTransactionLine` monthly series. Latest successful run on the office DB: #104
  (calc date 2026-10-27).
- **Coverage writer** (`coverage_writer.py`) writes `stkbal.maxnowqtymonths` (and `maxnowqty` when
  `COVERAGE_WRITE_MAXQTY`). The auto top-up fills missing coverage with one value for every item
  (`COVERAGE_AUTO_TOPUP_MONTHS`, code default 1.5). The office DB has 28 committed `CoverageTopUp` runs (success or
  partial). So SOFTECH's maximum is already being set uniformly. Any tier-based value there is a SOFTECH write.
- **The rate SOFTECH uses** is `stkbal.monthlyqty`, kept by the rate writer from the engine (method pivot =
  `monthly_avg`, or advanced = `policy_demand`; `SalesRatePush.method`).
- **Chronic item lists — three, of different sizes** (read-only counts, office DB 2026-10-31):
  - `catalog.ChronicMedication` (active): 331 items;
  - `chronic.ItemIngredientMap` → `ActiveIngredient.is_chronic`: 336 items;
  - `followups.ChronicMedicationProfile` (`is_chronic=True`): 3,302 items.
  - Customer side: `customers.CustomerHealthProfile.active_medications` (JSON list of items per customer) and
    `PurchaseHistoryLine`. Since the customer-link fix, sales without a PIC link to an `ACCT-<personcode>`
    placeholder, not a person (memory: sales customer link fix).
- **On-demand path exists:** `apps/reservations`, `apps/demand` (`DemandItem`), `apps/supply` (`DemandSignal`).
- **P-40 O3** (`apps/finance/cash_view.py` `_new_purchases(g, budget_weekly=None)`): run-rate per
  (supplier, category) over 13 weeks of real-supplier 10 − 120, placed at P-42 terms. One scalar `budget_weekly`
  rescales the whole mix for every week (the "what if").
- **The pivot sheet is now a P-31 input.** `pivot_sheets.record_snapshot` stores each download, and P-31 reads the
  `Total.الفرق-مطلوب/راكد` column. The default pivot must not change.

## 2. Scope

Three parts. Part 1 and Part 2 are read-only toward SOFTECH and do not change any existing order quantity.

### 2.1 Tier policy (proposed — owner confirms each value)

A pure module `apps/purchasing/cover_tiers.py`. `Decimal` throughout. Settings in `SystemSetting` `cover_tiers`
(JSON), defaults in code. Every change is audited (§2.4).

**Tier per (item, branch).** Rate = engine `monthly_avg` of the run, in SOFTECH packs per month.

| Tier | Proposed rule | Proposed target cover | Basis |
|---|---|---|---|
| Fast «سريع» | rate ≥ 4 | **1.0 month** | Measured bands (table §1). Card illustration. Fast items sit at ≈0.57 mo and carry 85% of estimated lost margin |
| Medium «متوسط» | 1 ≤ rate < 4 | **0.8 month** | Today's SOFTECH order point, unchanged |
| Slow «بطيء» | rate < 1 | **Presence** (below) | Measured bands; one pack of a slow item lasts months (pack rounding) |

**Presence and the on-demand rule (proposed).** For a slow item at a branch:
- **Presence = keep 1 whole pack** when any of these is true:
  1. **The item is on the chronic item list** (any branch). Owner rule: chronic-patient items are never on-demand.
     This spec reads it strictly: item-level, not only "a chronic customer at this branch" (open question 3).
  2. It sold at this branch in the last 6 months (`last_sale_date` ≥ run date − 6 months). Basis: the card, and the
     advanced engine's `dead_no_sale_months = 6`.
  3. It has an open reservation or demand line for this branch (`reservations`, `demand.DemandItem`). Proposed; to
     confirm.
- **Otherwise → «عند الطلب» (order on demand):** target 0. The item is not stocked by cover. A customer request goes
  through the existing reservation / demand path.
- **Chronic items are never on-demand, in any tier.** A chronic item's target is never below 1 pack, and a chronic
  fast or medium item keeps its tier cover. This is a hard rule in code with its own test.
- Presence never reduces a target: a slow item's target is `max(1 pack, rate × 0.8)` rounded the ISR way.

**Target and need** use the ISR rule's arithmetic, with the whole target scaled (no 1-month safety floor):
- target = rate × tier months (fast, medium) or the presence target;
- need = `isr_softech.softech_need(target, stock, transit)` (whole packs; under 0.16 pack → 0).
- Today's comparison line uses the same function with 0.8 months for every item.
- Not orderable lines are left out as `isr_softech._items` does today (non-stockable, `medicine_type 60`,
  `supplier_trans 2/3`).

### 2.2 Part 1 — read-only "what tiered cover would change" report

`build_tier_report(branch, run=None) -> dict` in `cover_tiers.py`. PostgreSQL only: the run's `ItemDemandMetrics`
and `Item`. No SOFTECH call. Pilot branch 160 first, then any branch 130–170 (not 100; HQ is not a cover target).

Per tier and in total, at **cost** (`Item.cost_price`; open question 5 on VAT):
- lines, stock value now;
- today's need (0.8 rule) and its value;
- tier need and its value;
- **extra cash needed** (fast, medium) and **cash no longer re-ordered** (slow on-demand);
- **stock above the tier target** (value) — cash that frees only as it sells or moves (P-27);
- counts: presence kept by reason (chronic / sold in 6 months / open demand); on-demand lines; chronic lines
  protected.

Per line (drill-down): item, tier, rate, stock, transit, last sale, chronic flag, presence reason, today's need, tier
need, value delta. The report states which run and which stock snapshot it used (the engine snapshot, not live
stock).

### 2.3 Part 2 — "within budget" ranking (advisory)

New `apps/purchasing/cover_budget.py`. It reuses Phase E, it does not copy it:
- Candidates = the tier report's lines with tier need > 0.
- Order = Phase E `priority_score` from `compute_row` (unchanged formula), ties broken by item code then branch code,
  so the order is reproducible.
- **Line cost = tier need × `Item.cost_price`** in `Decimal`, not Phase E's `rec_order_value` (sale price). A line
  without a cost price is shown as «بلا تكلفة» and is not funded.
- **Safety lane first (proposed):** chronic lines at zero stock or below presence are funded before the ROI order.
  Rule 4: safety beats margin. Owner confirms (open question 4).
- Then the greedy pass of `run_advanced_ranked`: fund while the running total fits; skip a line that does not fit.
- Output per line: rank, `ضمن الميزانية` yes/no, running total. Summary: budget, need, funded, deferred.
- **Nothing is ordered.** The buyer decides. No ISR draft or supplier order is created from this ranking.

**Purchase budget input.** Model `PurchaseBudget` in `apps/purchasing`:
- `week_start` (Saturday, as P-40), `amount` (EGP), `note`, `entered_by`, `entered_at`; one row per week.
- Who may enter it: open question 6.

**Interface for P-40.** `cover_budget.weekly_purchase_budget(week_starts) -> {date: Decimal | None}`.
- `cash_view._new_purchases` changes from one scalar to a per-week value:
  "what if" in the request (scalar, not stored) > `PurchaseBudget` for that week > the 13-week run-rate.
- The same supplier × category mix places each week's amount at P-42 terms (no change to that logic).
- O3's source chip reads «ميزانية الشراء» for weeks taken from the budget, «تقدير» for run-rate weeks.

### 2.4 Audit, API, screen, help

**Audit.** `apps/audit.AuditLog`, new actions `cover_tiers_changed` and `purchase_budget_changed`, with before /
after. The new choices need an `audit` migration.

**API** (`apps/purchasing/urls.py`)

| Endpoint | Method | Permission |
|---|---|---|
| `/api/purchasing/cover-tiers/report/?branch=&run=` | GET | `PURCHASING` |
| `/api/purchasing/cover-tiers/report/lines/?branch=&tier=&reason=` | GET | `PURCHASING` |
| `/api/purchasing/cover-tiers/budget/?branch=&budget=` | GET (ranking; `budget` not stored) | `PURCHASING` |
| `/api/purchasing/cover-tiers/settings/` | GET / PATCH | GET `PURCHASING`; PATCH admin |
| `/api/purchasing/purchase-budget/` | GET / POST / PATCH | per open question 6 |
| `/api/purchasing/cover-tiers/export/` | GET (xlsx) | `PURCHASING` |

Permissions are enforced on the server. Branch scope follows `core/branch_scope.py` (security Batch 5, not merged on
this branch).

**Screen.** A new tab on `/purchasing` (`PurchasingDashboard.jsx` `VIEW_TABS`): «🎯 التغطية حسب السرعة».
- `useHelpTab(viewTab)` already runs on this page; the new tab key gets its help section.
- Branch picker and every table and Excel column use branch names (`useBranchLabels` / `BL`), never a bare code.
- KPI strip: extra cash for fast, cash no longer re-ordered, stock above target, chronic lines protected,
  on-demand lines.
- Table by tier; a row click opens a side panel with the lines (no modal).
- One inline budget field (`useNumberInputGuards`) shows the «ضمن الميزانية» column. Entering a number does not
  save it; saving a week's budget is a separate small form.
- `DataFreshnessBar domains={['sales','stock','catalog']}` plus the run's calc date (the engine run has no
  freshness domain). The existing refresh and run buttons stay.
- A long report (all branches) runs with the existing `ProgressBar`.
- **Pivot sheet:** an optional «ضمن الميزانية» column only when a budget is given. Without a budget the pivot is
  byte-for-byte unchanged, so P-31 snapshots are not affected.

**Help** (`apps/help/content/purchasing.py`, Arabic + English)
- `purchasing.engine`: a new tab section for the new tab (tiers, presence, on-demand, chronic rule, budget column,
  "advisory only"); bump `updated`.
- `apps/help/content/finance.py` `finance.cash`: O3 now uses the weekly purchase budget when entered; bump `updated`.
- `apps/tests/test_help.py` must pass.

**Weekly summary** (for §4). Model `CoverTierWeekly`: `branch`, `week_start`, `run`, `summary` (JSON: per tier
lines, stock value, need values, on-demand and chronic counts). Saturday job `cover_tier_weekly_snapshot`,
idempotent per (branch, week).

**Migrations:** `purchasing/00xx_cover_tiers` (`PurchaseBudget`, `CoverTierWeekly`); `audit/00xx` (two action
choices). `SystemSetting` needs no migration.

### 2.5 Part 3 — later, not in this build

- Applying the tiers to the ISR rule (`isr_softech.plan_lines` target) or to the engine gap.
- Writing tier coverage to SOFTECH `maxnowqtymonths` / `maxnowqty` (coverage writer, auto top-up).
- The cash loop view (released by P-29 / P-31 / P-27, spent on cover, availability from P-30). It waits for P-27
  and P-30.

Each is its own proposal-to-build step with a stop-and-ask.

## 3. Acceptance criteria

- Tier assignment at the band edges (rate 0.99 / 1 / 3.99 / 4) follows the confirmed settings (test).
- **A chronic item is never on-demand** — at rate 0, with no sale in 6 months, at any branch, in any setting
  combination (test). A chronic fast item keeps fast cover (test).
- A slow non-chronic item with no sale in 6 months and no open demand is on-demand with need 0 (test). One with a
  sale in 6 months gets 1 pack (test).
- Need uses `softech_need` exactly: 0.15 pack → 0; 0.17 → 1; Decimal-safe (test). With every tier set to 0.8 and
  presence off, the tier need equals today's 0.8 need line for line (regression test).
- Report totals = sum of its lines to the piastre; values at cost price (test).
- Budget ranking: same inputs → same order and same funded set; ties by item then branch code; the safety lane
  (if confirmed) is funded first; a line without cost is never funded (tests).
- `weekly_purchase_budget` precedence: what-if > stored week > run-rate; weeks without a budget keep the run-rate;
  the O3 mix and P-42 placement are unchanged (tests in `test_cash_view.py`).
- **No SOFTECH call** in report, ranking or budget: tests patch `config.sybase.get_sybase_connection` to fail.
  No `IsrPush`, `SalesRatePush` or `CoverageTopUp` row is created (test).
- Default pivot export is identical with and without the feature (test).
- Users without `PURCHASING` → 403; settings PATCH admin only; every settings or budget change writes one
  `AuditLog` row with before / after (tests).
- Weekly snapshot is idempotent per (branch, week) (test). `test_help.py` passes.

**Tests**

| File | Proves |
|---|---|
| `apps/tests/test_cover_tiers.py` | bands; presence reasons; chronic never on-demand; need arithmetic; regression to the 0.8 rule; report totals at cost; no SOFTECH call |
| `apps/tests/test_cover_budget.py` | ranking order and ties; safety lane; cost basis; greedy skip; budget precedence for P-40 |
| `apps/tests/test_cover_tiers_api.py` | permissions, audit, drill-down = KPI, export, pivot unchanged, weekly snapshot |
| `apps/tests/test_cash_view.py` (extend) | O3 per-week budget, what-if still wins, run-rate fallback |
| `apps/tests/test_help.py` | new tab help; finance help updated |

## 4. Measurement

Pilot from the card: **branch 160 vs a comparison branch, 8 weeks, same budget share.** Report only during the
pilot; quantities change only after Part 3 is approved.

- **Report outputs at start** (baseline): extra cash for fast, cash no longer re-ordered, stock above target, per
  branch. To measure; no figure yet.
- **Slow-mover stock value** per branch, weekly (`CoverTierWeekly`). Baseline: 2.39M across 130–170 (run #104).
- **Fast / A-item availability:** measured by P-30 when built; until then the engine's estimate, labelled as an
  estimate.
- **GMROI** per branch (gross margin ÷ average inventory at cost) and **stock turns**. Margin basis per P-35
  (VAT caution). To measure.
- **Budget use:** weeks with a budget entered; funded vs deferred value; how many funded lines buyers actually bought
  (doc 10 lines vs the ranking; P-31 method).
- **On-demand service:** on-demand lines that got a customer request, and time to supply (reservations / demand).
  Target: no chronic line on-demand (0, by construction).

## Out of scope

- Any SOFTECH write: ISR quantities, `stkbal.maxnowqtymonths` / `maxnowqty`, rates. Stop-and-ask.
- Changing the SOFTECH-rule ISR, the engine gap, ABC coverage, or the default pivot sheet.
- Auto-ordering, ISR drafts or supplier orders from the ranking.
- The cash loop view (waits for P-27 and P-30).
- Any AI or model deciding a quantity, a tier or a budget. All rules are deterministic.
- Cleaning the chronic lists (only choosing which one counts, open question 2).

## Open questions / owner inputs

1. **Tier values.** Confirm the bands (fast ≥ 4, medium 1–4, slow < 1 packs per month, per item × branch) and
   cover (fast 1.0, medium 0.8, slow = presence). Or tier by ABC instead of velocity?
2. **Which chronic list counts:** `ChronicMedication` (331), the chronic-ingredient map (336),
   `ChronicMedicationProfile` (3,302), or their union? The union is the safest; the 3,302 list may include
   non-chronic items.
3. **On-demand rule.** Confirm: slow, not chronic, no sale at this branch in 6 months, no open demand → on-demand.
   Is "chronic" item-level (this spec) or only "an active chronic customer at this branch" (the card)? Is 6 months
   right? Should open reservations / demand keep presence?
4. **Safety lane:** fund chronic lines at zero or below presence before the ROI order?
5. **Cost basis for the budget:** `Item.cost_price` (pre-VAT) or the invoice cash outlay (VAT-inclusive for taxed
   items)? P-40 O3 uses `PurchaseLine.net_value`.
6. **Budget owner and cycle:** who enters the weekly purchase budget (buyers, finance, the owner) and is weekly
   (Saturday weeks, as P-40) the right cycle?
7. **Network roll-up:** the ranking is per item × branch, as Phase E. Should the budget instead be applied per item
   on the network purchase (the pivot's network gap after HQ stock)?
8. **Customer promise for on-demand items:** what delivery time does the branch state (next ISR, transfer, supplier)?
9. **Comparison branch** for the 8-week pilot.
10. **Supplier minimums and bonus deals:** shown as a note on the line, buyer overrides. Any rule wanted?

## Stop-and-ask

- Any SOFTECH write, including a tier value in `maxnowqtymonths` through the coverage writer or the auto top-up,
  and any change to ISR quantities (Part 3). Each needs its own confirmation and a reviewed dry-run.
- Changing the default pivot sheet or its `Total.الفرق-مطلوب/راكد` column (P-31 depends on it).
- Changing the P-40 O3 placement rule beyond the budget source (it is a built finance view).
- Linking the ranking to automatic ordering or supplier payment.
