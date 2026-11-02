# 06 · SPEC P-32 — One authority per replenishment decision (consolidate, not retire)

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
Depends on doc 30 phase B (plan ledger + wave 0). Every SOFTECH write stays in the existing ISR writer, behind its
gate and guards. No new SOFTECH writer.

**Owner input** (ledger row P-32 and the backlog revision; these override the backlog card)
- **Consolidate, not retire.** Nothing is deleted: no engine, no model, no table, no screen.
- The owner built transfer recommendations and the advanced engine to be used. Transfers and turnover are a direct
  cash lever.
- **TransferEngine → a wave inside توزيعة**, with doc 30's whole packs, value threshold and wave order, instead of
  thousands of fractional recommendations per run on a separate screen.
- **Advanced engine Phase E** (cash-budget ROI ranking) → **P-34**. Not built here.
- Item forecasts feed the gap, or stop (owner to choose, open question 4).
- The shortage-sheet gap stays the buying authority. The owner confirms buyers use it.

## 1. Problem (measured)

- **About six planners answer "how much, and from where"**, and none has a stated authority (02 §3.1, §7):
  DemandEngine, AdvancedEngine, SOFTECH-rule ISR vs engine-rule ISR, TransferEngine, L3 توزيعة, the ISR fulfilment
  donor plan, plus the shortage stock check.
- **TransferEngine output has no consumer:** `TransferRecommendation` 527,841 pending / 1 approved / 7 rejected;
  168k generated in 30 days (02 §1). 0.2 GB of the database (backlog, Batch 8 card).
- **توزيعة today** (doc 30 §1, measured 2026-10-24): 5,226 suggestions per analysis; one «توليد» = 45 ISR drafts;
  97% of moves start at a branch (two legs through HQ); 2,586 branch-sourced moves worth < 100 EGP;
  **1,169 suggested (item → branch) pairs already in a SOFTECH HQ ISR from the last 3 days**; 64 already in transit.
- **Double-post risk, found 2026-10-24** (doc 30 §1 defect 1): drafts **#30 and #32 were identical to #29**
  (HQ → 160, 5,174 lines, 1.91M), which was already pushed to SOFTECH. Approving either would have sent the same ISR
  twice. Pressing «توليد» twice made all 45 drafts twice. Phase A (built 2026-10-25) cancelled #3–#8, #30, #32–#34 and
  added guards. The risk that remains is **overlap**, not identical copies: the push guard only refuses an ISR whose
  lines are *identical* to one pushed on the same route in 7 days. A draft that repeats part of a pushed ISR, or
  of SOFTECH's own daily ISR, still passes.
- **The ISR screen offers an unexplained rule choice:** «مثل SOFTECH» (default) or «فجوة المحرك (القديمة)».
  SOFTECH's rule gave 2,082 lines / 0.99M where our engine rule gave 5,174 / 1.91M on the same day for branch 160
  (`isr_softech.py` docstring).

**Code facts that shape the build** (read in the repo)
- **TransferEngine has no scheduler job of its own.** It runs as MODULE 12 inside `DemandEngine.run`
  (`apps/purchasing/engine.py:426-434`). The engine runs from the `demand_engine_scheduled` job
  (`apps/sync/tasks.py`, Sun + Wed, gated by `DEMAND_ENGINE_SCHEDULE_ENABLED`) or from the dashboard. "Stop the job"
  therefore means "stop MODULE 12 writing rows", not "remove a job".
- **TransferEngine consumers** (all read the latest `TransferRecommendationRun`):
  - `/purchasing` tab «🔄 التحويلات المقترحة» (`TransferRecsTab` in `frontend/src/pages/PurchasingDashboard.jsx`;
    `/api/purchasing/transfer-recs/…` in `apps/purchasing/views.py`). Approve only records a status.
  - `/supply` ISR tab inter-branch picker: `isr_transfer_preview`, `isr_transfer_export`, `isr_transfer`
    (`apps/purchasing/isr_views.py`) → `isr_writer.generate_transfers_from_run` → `create_transfer_proposals`
    (L2 linked legs). Same path in `manage.py generate_transfer_isr`.
  - `supply_exports.transfer_pairs_excel`.
  - `LostSalesEngine` root cause 2 `transfer` (`apps/purchasing/lost_sales_engine.py`, SQL `transfer_pairs` CTE on
    `purchasing_transferrecommendation`).
  - `apps/supply/engine/allocation.py` imports `MIN_TRANSFER_QTY` and copies the surplus rule for `allocate_internal`
    (SupplyCase recommendations, `supply/engine/recommend.py`).
  - Retention: `apps/sync/maintenance.py::prune_engine_runs` already deletes pending recommendations of pruned runs
    (P-56).
- **Three different donor rules** decide how much a branch may give:
  - TransferEngine and `allocate_internal`: `current_stock − safety_stock`, fractional, ≥ 0.5 unit.
  - توزيعة (`distribution.py::_pick_surplus`): stock above the branch's SOFTECH ceiling (`maxnowqty`), whole packs.
  - ISR fulfilment (`isr_fulfillment.py`): stock above `rate × donor coverage` (`DEFAULT_DONOR_COVERAGE` 1.0 month),
    whole packs.
- **Three planners compete for one draft slot.** The constraint `isrpush_one_live_draft_per_route` (purchasing 0037)
  allows one live *general* draft per (kind, source, destination). Replenishment (`create_proposal`, HQ → branch),
  L2 transfer legs and توزيعة (`create_distribution_proposals`) all make general drafts. So a توزيعة run
  **cancels a waiting replenishment draft on the same HQ → branch route** (audited by `isr_guards.retire`, but the
  person who made the first draft is not told). Request-tied drafts (`origin_isr`, `origin_request`,
  `origin_shortage_list`) have their own constraints and are not affected.
- **Guards that exist** (`apps/purchasing/isr_guards.py`): route validation, one live general draft per route,
  identical-lines push guard (`DUP_PUSH_DAYS = 7`, override needs a reason, audited), feeder-leg-first, cancel with
  reason. `push_isr_record` takes a Postgres advisory lock per draft and re-reads the status. **Not built:** draft
  expiry (doc 30 §2.6), wave 0 (subtract committed flows).
- **Engine rule on the ISR screen:** `isr_views.isr_propose` reads `rule`; `create_proposal(rule='engine')` uses
  `isr_writer.build_plan` (the engine gap re-scaled by coverage). The select is in `SupplyPage.jsx` (ISR tab).
- **Advanced engine** (`advanced_engine.py`) is export-only (`/api/purchasing/advanced-export/`,
  `advanced-pivot-export/`) **and** a rate method of the sales-rate writer (`rate_writer.py`, method `advanced`). It is
  already an input, not a planner.
- **Forecast fields are read by one rule.** The card says `forecast_30d/90d` are read by nothing. In code,
  `ForecastService` (job `sales_forecast`, 02:30) writes `ItemDemandMetrics.forecast_next_30d/90d`, and
  `insights.rules.rule_demand_surge_unmet` reads `forecast_next_30d`. The gap does not use them.
- **Buying gap:** `ItemDemandMetrics.gap` from the DemandEngine, exported as the demand pivot
  (`Total.الفرق-مطلوب/راكد`, `apps/purchasing/pivot_sheets.py`; P-31).

## 2. Scope

### 2.1 The authority table

| Decision | Current authorities (file / model) | Single authority after P-32 | What the others become |
|---|---|---|---|
| **How much a branch needs from HQ** (replenishment ISR) | `isr_softech.build_plan` (SOFTECH rule, default); `isr_writer.build_plan` (engine gap, `rule='engine'`); SOFTECH's own native daily ISRs | **SOFTECH-rule ISR** (`isr_softech.build_plan` → `create_proposal(rule='softech')`) | Engine gap = a read-only **reference column** on each ISR line. `rule='engine'` stays in code and the API (lab use, open question 1); the screen select is removed. Native SOFTECH ISRs = **input** to wave 0 |
| **What moves between branches, network-wide** (proactive + shortage-driven) | TransferEngine → `TransferRecommendation`; L3 `distribution.analyze` → `create_distribution_proposals`; L2 `generate_transfers_from_run` | **The توزيعة plan** (doc 30 phase B: `DistributionPlan` + `PlannedMove`), with a new **shortage wave** | TransferEngine's matching → the shortage wave's **input**. `TransferRecommendation` table and `/purchasing` tab → **read-only history**. L2 picker on the ISR tab → shows the shortage wave of the current plan |
| **Answering one branch's request** (SOFTECH ISR, WhatsApp, shortage list) | `isr_fulfillment.compute` + `create_donor_returns` / `create_request_transfers` (already one planner since P-33) | **ISR fulfilment planner** (unchanged) | Its live legs are **input** to wave 0, so the network plan never moves the same need again |
| **How much a donor branch may give** | three rules (see code facts) | **One donor rule** in one function, used by all three planners (owner choice, open question 2) | `allocate_internal` (supply cases) and the TransferEngine call the shared rule |
| **What to buy** | DemandEngine gap (demand pivot); advanced engine `rec_order_qty` (export); fulfilment residue "shortage to purchase"; SupplyCase recommendation | **Engine gap on the shortage sheet** (`ItemDemandMetrics.gap`, demand pivot) | Advanced engine = **lab export** + rate method; Phase E ranking → **P-34**. Fulfilment residue and SupplyCase = **views** that show the gap figure |
| **Why a sale was lost (transfer cause)** | `LostSalesEngine` reads pending `TransferRecommendation` | **The current توزيعة plan** (a live `PlannedMove` or live leg to that branch) | — |
| **Forecast next 30/90 days** | `ForecastService` → `forecast_next_30d/90d` | Owner choice (open question 4) | Insight rule `rule_demand_surge_unmet` keeps reading it either way |
| **Cash-budget ranking** | advanced engine Phase E (`run_advanced_ranked`) | **P-34** (separate spec) | Unchanged here |

### 2.2 Shortage wave inside توزيعة
- Built on doc 30 phase B (plan ledger, wave 0, live inputs). P-32 adds the parts of phase C the shortage wave needs:
  wave order, whole packs, value thresholds.
- **Deficit** = the SOFTECH-rule need of the receiving branch (authority row 1), after wave 0. Not the engine gap.
- **Donor** = the shared donor rule (row 4). Whole packs only. Moves below the line threshold (doc 30 §2.4, default
  100 EGP per line, 1,000 EGP per route) are dropped, unless the source is HQ.
- **HQ first.** If HQ holds the item, the need belongs to the replenishment ISR (row 1), not to a transfer.
- **One move per (item, from, to)**, whatever wave found it. Reasons kept as tags (`shortage`, `over_piled`, …).
- **Wave position:** proposed after wave 1 (HQ first) and before wave 2 (over_piled), because it serves a real
  stock-out. Owner confirms (open question 3).
- `TransferEngine` code stays. Its greedy match is reused with the shared donor rule, whole packs and the thresholds.
  It writes `PlannedMove` rows, not `TransferRecommendation` rows.
- MODULE 12 stops writing `TransferRecommendation` behind a setting `TRANSFER_RECS_LEGACY_ENABLED` (default True until
  the shortage wave is accepted, then False). Code, model and table stay; old rows age out by P-56 retention.

### 2.3 One live draft per route, whoever made it
- Every general `IsrPush` records its planner in `params['planner']` (`replenishment`, `distribution`). No schema
  change.
- A new general draft from one planner **does not supersede** a live draft from another planner on the same route.
  It is refused with the other draft's number and planner (new `GuardError` code `other_planner`). Same-planner
  supersede stays as today.
- Wave 0 already treats a live replenishment draft as committed, so توزيعة simply leaves those lines out.
- If the owner wants the two documents to live side by side, that needs a `purpose` column in the route constraint —
  a schema change on the writer's staging table (open question 5, stop-and-ask).

### 2.4 No double-posting (wave 0 + push guard)
- **Wave 0** (doc 30 §2.2) subtracts, per (item, destination): open SOFTECH ISRs to that branch (server 100, last
  N days, not dispensed), our live and pushed-not-dispensed `IsrPush` lines (all origins), in-transit transfers
  (14-day rule) and live fulfilment / WhatsApp / shortage-list legs. A move that would repeat one is listed under
  «متعارض» with the covering document.
- **Push-time overlap check** (extends `isr_guards.check_push`): before writing, each line is compared again with
  pushed ISRs on the same destination in the last `DUP_PUSH_DAYS`. Overlapping lines are listed; the push is refused
  unless a reason is written (same rule and audit as the identical-lines guard). This catches a plan made before
  another push landed.
- **Built 2026-11-01, switched OFF:** `isr_guards.overlapping_pushed` + the overlap step in `check_push`
  (refused `overlap_push` without a reason; with a reason → `params.forced_overlap` + AuditLog
  `isr_overlap_push_forced`). Overlap = same kind and destination, pushed in the last `DUP_PUSH_DAYS` (7), sharing
  at least one item; an identical ISR stays with the duplicate guard. Switch: SystemSetting `isr_overlap_guard` = on.
  `report_isr_overlaps --days 90` measures it read-only: on 2026-11-01 only 1 ISR was pushed from our side in 90 days
  (0 overlaps), so the daily-route effect is unknown.
- **Owner 2026-11-01: a repeat counts only while the earlier ISR is not dispensed.** Dispensed = the earlier ISR's
  source issued that item to that destination after the push (stock-ledger mirror, doc 125 «صرف لفرع», counterpart
  store = destination — verified on HQ issue lines: `storecode2` and `personcode` = the receiving branch). SOFTECH
  does not put the ISR number on the issue line (`s_doccode` empty, `r_doccode` points to purchases), so the rule is
  item × route × time. The ledger refreshes every 2 h: a very recent issue still asks for a reason (safe side).
- **Switched ON 2026-11-01** by the owner (SystemSetting `isr_overlap_guard` = on, office database).
- **Built 2026-11-01 — planner rule (§2.3), live:** `_persist_proposal(planner=…)` records `params['planner']`
  (`replenishment` from `create_proposal`, `distribution` from «التوزيعة», `transfer` from the engine pairs);
  `check_route_free` refuses a proposed draft of another planner with `other_planner` instead of cancelling it.
  Drafts made before planners were recorded still supersede as before.
- **Built 2026-11-01 — draft expiry, OFF:** `isr_guards.expire_drafts` + daily 06:30 job `isr_draft_expiry` cancel
  (with audit) PROPOSED general drafts older than SystemSetting `isr_draft_expiry_days`; 0 / missing = off. Approved
  and request-tied drafts are never expired.
- **Draft expiry switched ON 2026-11-01** by the owner: `isr_draft_expiry_days` = 7. First run would cancel the 3
  proposed general drafts then open (#1 150 self and #2 170 self, 19 Sep; #31 100 → 150, 20 Oct).
- **Draft expiry** (doc 30 §2.6): an unpushed general draft older than N days (default 7) is cancelled with audit by a
  daily PG-only job `isr_draft_expiry`. It never touches SOFTECH.
- Regenerating a plan supersedes the old plan's drafts (same planner). It never duplicates them.

### 2.5 Screens
- `/supply` «طلبات التوريد / ISR»: the rule select goes. Lines show «فجوة المحرك» as a reference column. The
  inter-branch picker shows the current plan's shortage wave, read-only, with a link to «التوزيعة».
- `/supply` «التوزيعة»: the shortage wave appears in wave order with its totals and the «متعارض» panel (doc 30 §2.8).
  Grids use `useGridKeyboard`; branch names via `useBranchLabels` (no bare codes, also in Excel);
  `DataFreshnessBar` with the plan's read time and a refresh button.
- `/purchasing` «🔄 التحويلات المقترحة»: a read-only history with a note «التحويلات الآن ضمن التوزيعة» and a link.
  Approve/reject buttons hidden; the PATCH endpoint returns 410 when `TRANSFER_RECS_LEGACY_ENABLED` is False.
- No new modals.

### 2.6 Help
- `apps/help/content/purchasing.py`, Arabic + English, bump `updated`:
  - `purchasing.supply` (`/supply`): tabs `isr` (no rule choice; engine gap as reference), `dist` (shortage wave,
    «متعارض», draft expiry), and one line on who decides what (the table in §2.1, short).
  - `purchasing.engine` (`/purchasing`): tab `transfer` becomes history; remove the advice "start with suggested
    transfers" in the tips and the tour step `purchasing-engine-view-tabs`.
- `SupplyPage.jsx` and `PurchasingDashboard.jsx` already call `useHelpTab`; keep them wired.

### Files
- `apps/purchasing/distribution.py` (shortage wave), `transfer_engine.py` (shared donor rule, `PlannedMove` output),
  new `apps/purchasing/donor_rule.py`, `isr_writer.py` (planner tag), `isr_guards.py` (`other_planner`, overlap,
  expiry), `engine.py` (MODULE 12 flag), `lost_sales_engine.py` (transfer cause from the plan),
  `isr_views.py`, `views.py` (transfer-recs PATCH), `apps/supply/engine/allocation.py`, `apps/sync/tasks.py`
  (`isr_draft_expiry`), `config/settings` (`TRANSFER_RECS_LEGACY_ENABLED`).
- Frontend: `frontend/src/pages/SupplyPage.jsx`, `frontend/src/pages/PurchasingDashboard.jsx`,
  `frontend/src/api/client.js`.
- Help: `apps/help/content/purchasing.py`.
- **Migration:** none for P-32 itself. `DistributionPlan` / `PlannedMove` come with doc 30 phase B.

## 3. Acceptance criteria

- **No double post.**
  - Generating the plan twice → the same number of live drafts; the first set superseded, audited (test).
  - A move whose (item, destination) is in a SOFTECH ISR from the last N days, a live or pushed `IsrPush`, a live
    request leg or an in-transit transfer → not drafted; listed «متعارض» with that document (test per source).
  - Pushing a draft that overlaps a pushed ISR on the same destination → refused without a reason; with a reason →
    pushed once and audited (test).
  - Two concurrent pushes of one draft → one SOFTECH write (existing lock test still passes).
  - With `ISR_WRITER_ENABLED` off or `writer_allowed` false, nothing reaches SOFTECH (existing tests pass).
- **One slot per route.** A توزيعة draft does not cancel a live replenishment draft on the same route; it is refused
  with `other_planner` and the other draft's number (test). Same-planner supersede unchanged (`test_isr_guards.py`).
- **Shortage wave.** Whole packs only; no move below the thresholds unless from HQ; a donor never goes below the
  shared donor rule; HQ-held items are never transfer moves; one move per (item, from, to) (tests).
- **Same donor answer everywhere.** The same stock fixture gives the same donor quantity from توزيعة, ISR fulfilment
  and `allocate_internal` (test).
- **Legacy kept.** With `TRANSFER_RECS_LEGACY_ENABLED=False`, a DemandEngine run writes 0 `TransferRecommendation`
  rows and the old rows stay readable; with True, behaviour is as today (test).
- **Lost-sales cause.** `transfer` is set from a live `PlannedMove` / leg to the branch, and not from
  `TransferRecommendation` (test).
- **ISR screen.** `isr_propose` without `rule` uses the SOFTECH rule; each line carries the engine gap figure (test).
- **Expiry.** A general draft older than N days is cancelled with audit; a request-tied draft is not (test).
- **Permissions.** Plan generation and draft creation use the existing server-side purchasing write check
  (`isr_views._can_write` → `apps/purchasing/access.py::can_supply_write`); a branch user → 403 (test).
- `test_help.py` passes.

**Tests**

| File | Proves |
|---|---|
| `apps/tests/test_isr_guards.py` (extend) | `other_planner` refusal; overlap push guard + reason; expiry |
| `apps/tests/test_distribution_shortage_wave.py` (new) | wave order, whole packs, thresholds, HQ first, dedup, wave 0 conflicts per source, regenerate supersedes |
| `apps/tests/test_donor_rule.py` (new) | one donor answer for the three planners |
| `apps/tests/test_isr_writer.py`, `test_isr_softech.py`, `test_isr_fulfillment.py`, `test_shortage_transfers.py`, `test_supply_engine.py`, `test_distribution_ceilings.py` | still pass (regression) |
| `apps/tests/test_lost_sales_cause.py` (new) | transfer cause from the plan |
| `apps/tests/test_help.py` | help for the changed tabs |

## 4. Measurement

- Duplicate or overlapping ISR lines pushed to SOFTECH per month. Target **0** (unforced). Baseline: to measure
  (read-only, `IsrPush` pushed lines vs SOFTECH ISRs on the same destination within 7 days).
- Drafts per «توليد». Baseline 45 (doc 30). Target ≤ 10 (doc 30 §2.5).
- «متعارض» moves caught by wave 0 per run. Baseline 1,169 overlaps with SOFTECH ISRs (doc 30, 2026-10-24).
- `TransferRecommendation` rows written per 30 days. Baseline 168k (02 §1). Target 0 after the switch.
- Shortage-wave moves drafted, pushed and received per week. Baseline 1 approved recommendation ever.
- Planners a buyer must look at for one decision: before 6, after 1 (ask the buyers).
- Database size of `TransferRecommendation`. Baseline 0.2 GB; then shrinking by P-56 retention.

## Out of scope

- P-34 (Phase E budget ranking, velocity tiers, coverage-writer changes).
- Doc 30 waves 2–4 beyond what the shortage wave needs (P-27 builds the dead-stock lane).
- Deleting any engine, model, table, endpoint or screen.
- Changing SOFTECH's rule, the ISR writer's SOFTECH SQL or the approve step.
- Changing the buying gap formula. Feeding forecasts into it is open question 4 and a separate change.
- Merging the shortage stock check into supply (done by P-33 (a)).

## Open questions / owner inputs

1. **Engine rule on the ISR screen:** remove the select and keep `rule='engine'` for lab/API use only (proposed), or
   keep it behind an «متقدم» toggle?
2. **One donor rule:** donor keeps (a) `rate × 1.0 month` as in ISR fulfilment (proposed: same as the request
   path), (b) the SOFTECH ceiling `maxnowqty` as in توزيعة, or (c) safety stock as in TransferEngine?
3. **Shortage-wave position:** after HQ first and before over_piled (proposed)?
4. **Forecasts:** feed `forecast_next_30d` into the gap, or stop the `sales_forecast` job? If stopped,
   `rule_demand_surge_unmet` loses its input (change it to the rate, or retire the rule).
5. **Replenishment and توزيعة on the same HQ → branch route:** refuse the second (proposed, no schema change), or let
   both coexist (adds a `purpose` field to the route constraint; schema change)?
6. **Doc 30 decisions still open:** thresholds (100 / 1,000 EGP), wave order, «بعد الاستلام» waits for push or
   receipt, draft expiry days (7), and N days of SOFTECH ISRs for wave 0.
7. **Parallel run:** how many engine runs to keep `TRANSFER_RECS_LEGACY_ENABLED=True` while comparing the shortage
   wave with the old recommendations? Proposed: two runs (one week).
8. **Buyers:** confirm they use the demand pivot gap to buy (ledger condition).

## Stop-and-ask

- Every SOFTECH write stays the existing gated ISR push (`ISR_WRITER_ENABLED`, `writer_allowed`, single writer
  instance). Confirm before turning any planner's drafts into pushes; nothing pushes automatically.
- Any change to `isr_guards.check_push` or the supersede rule touches the double-post guard of a live SOFTECH writer.
  Confirm the overlap rule and the `other_planner` rule before build.
- Open question 5 option (b) is a schema change on `IsrPush`. Confirm first.
- `DistributionPlan` / `PlannedMove` (doc 30 phase B) are new tables; confirm with doc 30's approval.
- The office is the writer instance until the VPS cutover (P-54). Build and test against a test database only; never
  run plan generation or pushes against the office database during development.
