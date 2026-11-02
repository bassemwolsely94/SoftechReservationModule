# 06 · SPEC P-30 — Measured availability for top sellers + a daily "out here, in stock there" list

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
Read-only toward SOFTECH. No new SOFTECH read job and no new SOFTECH writer. Wave 2 (stock and availability).
Feeds P-34 (measured availability) and P-47 / P-49 (availability-driven lost demand).

**Owner input** (ledger row P-30 and the backlog revision; these override the backlog card)
- **List owners:**
  - the HQ main-warehouse **store specialists** get the **network list** ("out at a branch, in stock at HQ or another
    branch");
  - **branch salespeople** see **their own branch's list**.
- The list replaces phone and WhatsApp escalations for non-urgent cases. It is visible before the next ISR.
- **Pilot branch: 160.**
- **Dependency: the ledger `newqty` meaning must be verified first** ("20-sample check"). Nothing is built on
  `newqty` until step 0 passes.

## 1. Problem (measured)

- **Availability is estimated, not measured.** `apps/purchasing/lost_sales_engine.py` has "no day-by-day stock
  history". It sets `stockout_days = expected sale days − actual sale days` (capped at 30). It cannot tell "no customer
  came" from "no stock". A-item availability (94–98%) and lost revenue (≈390k/30d) are model outputs (backlog P-30).
- **The "transfer" root cause is ≈142k/30d (estimated).** This is stock that was in the network and was not moved
  (backlog P-30).
- **Fast movers are thin.** Run #104, branches 130–170: fast items (≥4/mo) have ≈0.57 months of cover; 392
  item×branch pairs at zero; estimated lost margin 69k/30d, 85% of the estimate (backlog, "Measured cash vs
  availability").
- **The data to measure it exists.** The stock ledger covers branches 100/130/140/150/160/170, 97k–319k lines per
  branch per year. At branch 160, 412 of 712 moving A items hit 0 within 90 days (03 data map, Batch 3). Whether
  `newqty` is per store or per branch is **unverified** (class B).
- **No screen says, this morning, "these top sellers are at zero here, and HQ or branch X has them".**
- Sales understate demand: they are capped by availability (03, analytical cautions). `pos_cancel` is mostly cashier
  corrections, so it is not a lost-sales source (03).

**Code facts that shape the build** (read in the repo)
- **Ledger:** `stock_audit.StockLedgerLine` (`apps/stock_audit/models.py`). It holds `branchcode`, `storecode`,
  `storecode2`, `doccode`, `docnumber`, `docdate` (date only), `trans_time` (nullable), `itemcode` + `item` FK,
  `transqty`, `newqty` (help text "Stock after this line"). Index `sa_ledger_item_br_time` = (`itemcode`,
  `branchcode`, `trans_time`).
  - Filled by `apps/stock_audit/ledger.py::sync_ledger` from **HQ only**. HQ holds every branch's lines (doc 32
    Phase 0: branch 160 158,430 = 158,430). The query is a `docdate` range (index `stktrans_60`); `trans_time` is
    unindexed in SOFTECH.
  - Schedule (`apps/sync/tasks.py`): `stock_ledger_sync` every 2 h at :10 from 08:10 to 22:10 (replaces the last
    3 days); `stock_ledger_catchup` 03:15 (7 days + prune). Window `STOCK_AUDIT_WINDOW_DAYS` = 365. Size ≈3,000
    lines/day, ≈1.1M rows a year (doc 32 §4 D1).
  - Freshness domain `stock_audit` (`apps/sync/freshness.py`, cadence 120 min).
- **A stock-out check already exists:** check 6 `frequent_stockout` (`apps/stock_audit/rules.py::check_frequent_stockout`)
  counts `newqty = 0` after a 115/125/150/180 line, medicines only, in the /stock-audit «availability» group. It counts
  events; it does not measure duration. P-30 reuses its definitions; it does not replace the check.
- **Current stock:** `catalog.ItemStock` (`quantity_on_hand` = `stkbal.nowqty`, `monthly_qty`, per
  `softech_store_code`; unique item × branch × store). Freshness domain `stock` (fast lane).
- **Selling store of a branch:** `apps/purchasing/rate_writer.py::resolve_store` (default = the branch code;
  `SALES_RATE_STORE_MAP` overrides, empty today in `config/settings.py`).
- **HQ store roles:** `apps/batches/store_roles.py` (P-26). HQ real-balance stores are 100 + 104; 102/103/105 are
  quarantine and 110 is a closed branch, excluded everywhere (isr_fulfillment docstring; ledger P-26).
- **Engine rates and ABC:** `purchasing.ItemDemandMetrics` (`monthly_avg`, `abc_class`, `current_stock`,
  `in_transit_qty`, `coverage_days`, `stockout_days_30d`, `availability_rate_30d`, `pack_price`). **ABC is network
  level** (`engine.py::_classify_abc`, Pareto on network monthly value), not per branch. The engine runs Sunday and
  Wednesday nights (`demand_engine_scheduled`). Latest run: `rate_writer._latest_run()`.
- **In transit:** `apps/purchasing/in_transit.py::by_branch_code` (the same definition the engine nets out).
- **Donor surplus rules:** `apps/purchasing/isr_fulfillment.py`: `ceiling(rate, months)`, `_excess(stock, cap)` (whole
  packs above the ceiling), `DEFAULT_DONOR_COVERAGE = 1.0` month, `coverage_need`, and the owner rule "HQ fills alone
  when its whole packs cover the request".
- **Transfer path (P-33 (a), built):** a `shortage.ShortageList` → `GET/POST /api/shortage/lists/<id>/transfer-plan/`
  and `.../transfers/` → `isr_fulfillment.create_request_transfers(..., shortage_list=…)`. It makes two linked
  PROPOSED `IsrPush` legs per donor (donor → 100 → branch), guarded by the constraint
  `isrpush_one_live_leg_per_list_donor`. These drafts never supersede the daily route draft.
  - **Gap:** `create_request_transfers` only makes legs for **donor branches**. The plan's `from_hq` part becomes no
    ISR. The HQ part reaches the branch only through the daily HQ → branch route ISR.
  - `ShortageList.source` is a free `CharField` (max 30; "manual | ocr | imported"), so a new value needs no migration.
- **Branch hours:** `branches.BranchSettings.is_24h` + `working_hours` (doc 32 D3; used by check 9).
- **Safety:** `apps/catalog/safety.py::item_safety_flags` / `blocks_sale` (return only, sale stopped, …).
- **Permissions:** `apps/purchasing/access.py::can_supply_write` (admin, purchasing, supply SOFTECH groups);
  `core/branch_scope.py` (`scope`, `allows`, `sees_all_branches`).

## 2. Scope

The build has four steps. Each step needs its own go-ahead. Step 0 is a gate.

### Step 0 — `newqty` verification (read-only; PG mirror + a person's check in SOFTECH)
New command `verify_ledger_newqty --branch 160 [--sample 20]`. It reads PG only and writes a report file (no
database writes):
1. **Store mix.** For branch 160 lines in the window: share of lines whose `storecode` ≠ `resolve_store(branch)`;
   and the stores seen. If a branch has two selling stores, the spell logic runs per store (see step 1).
2. **Chain consistency.** For consecutive lines of the same (branch, store, item), ordered by (`trans_time`,
   `docnumber`): does previous `newqty` ± `transqty` = this `newqty`? The doccode meanings come from
   `apps/finance/queries/sybase_finance.py`; the in/out direction per doccode is inferred from the data and listed
   for the owner to confirm. Report the % consistent, and the doccodes that break it.
3. **End state.** For items with no line since the last `ItemStock` sync: last `newqty` vs
   `ItemStock.quantity_on_hand` for the same store. Report % equal.
4. **Units and signs.** Distribution of fractional `newqty` (strip sales) and of `newqty < 0`.
5. **20-sample sheet.** Picks 20 item × date cases at branch 160 (10 that reach 0, 10 that do not). A store
   specialist opens each item card (كارت الصنف) in SOFTECH and writes the balance seen after the listed line. **No
   new SOFTECH query is run by us.**

**Pass rule (proposed; owner confirms):** at least 19 of 20 samples match, and checks 2–3 are at least 95%
consistent on branch 160. A fail → stop and report. No step 1 build on an unverified field.

**Step 0 — first run, 2026-10-31** (`verify_ledger_newqty --branch 160`, 2 Aug – 31 Oct, PostgreSQL mirror only;
built in `apps/stock_audit/newqty_check.py`):
- 82,374 lines, **all at store 160** (the selling store). One store per branch, so spells run per branch here.
- **Chain consistent 75,279 / 75,794 = 99.3 %.** Of the 515 breaks, 376 sit between two lines on the same day and 28
  share the same entry time, so the likely cause is line order, not a wrong balance.
- **End state equal 6,115 / 6,345 = 96.4 %** (last `newqty` vs `ItemStock` where no line came after the stock sync).
- **Units:** 27,594 lines have a fractional balance (strip sales), so `newqty` is in packs with strip fractions. **No
  negative balances.** 7,963 lines end at zero.
- **Direction per document, as inferred from the data (owner to confirm):** in — 10 purchase, 25 receipt from a branch,
  30 customer return, 50 count surplus, 20, 80, 81; out — 115 sale, 120 return to supplier, 125 issue to a branch,
  150 count shortage, 180, 181.
- **Verdict: checks 2 and 3 pass (≥ 95 %); waiting for the 20-case sheet** («عينة للتحقق» in the report), to be
  checked by a store specialist on the SOFTECH item card, then scored with `--score <file>`.

### Step 1 — measured stock-out spells + availability (PG only, nightly)
New module `apps/stock_audit/availability.py`.
- **Scope of items.** Per branch, item × selling store where:
  - `abc_class` in A/B in the latest successful engine run; and
  - the branch's own `monthly_avg` ≥ `ls_min_daily_demand` × 30 (the lost-sales engine's existing floor,
    `EngineConfig`).
  - Store 110 and quarantine stores are never in scope (P-26).
- **Spell rule (deterministic).**
  - A spell **starts** at the `trans_time` of a line with `newqty ≤ 0`.
  - It **ends** at the `trans_time` of the next line at the same (branch, store, item) with `newqty > 0`. With no
    such line, the spell stays open.
  - **State at the window start** = `newqty` of the last line before the window. The ledger keeps 365 days and the
    report window is 90, so this is known. An item with no line in the whole ledger keeps `ItemStock` stock all
    window; it is marked `no_movement`.
  - `trans_time` null → `docdate` 00:00, and the spell is marked `time_estimated`.
- **Open hours.** Durations count only the branch's open hours (`BranchSettings`). A branch with no hours set →
  24 h, and the result is marked `hours_unset`.
- **Measures per item × branch × day:** open minutes, minutes out of stock, in stock (yes / no by the day rule
  below).
  - Day rule: a day is "out" when its out-of-stock minutes ≥ `availability_day_out_share` × its open minutes
    (SystemSetting, proposed default 0.5; owner confirms).
- **Lost sales (measured spells, estimated demand).**
  - lost units = (out minutes ÷ open minutes per day) × (`monthly_avg` ÷ 30);
  - lost value = lost units × `pack_price`;
  - lost margin is shown only on the P-35 margin basis. Until P-35 is settled it is labelled "unverified basis":
    `pack_price` is VAT-inclusive and cost is pre-VAT (03 cautions).
  - The rate itself is understated during long stock-outs. The screen says so.
- **Calibration.** For the same item × branch pairs, measured out-days in the last 30 days vs the engine's
  `stockout_days_30d` / `availability_rate_30d`. This comparison is the first output of the card. **The engine
  estimate is not changed** (see stop-and-ask).
- **Models** (new tables in `stock_audit`):
  - `AvailabilityRun`: started/finished, status, window, branches, `engine_run` FK, `ledger_sync_run` FK, params
    snapshot, counts, `rules_version`.
  - `StockoutSpell`: `branch`, `branchcode`, `storecode`, `item`, `itemcode`, `started_at`, `ended_at` (null = open),
    `start_line_ref` / `end_line_ref` (branch, doccode, docnumber, docdate), `open_minutes_out`, flags (JSON:
    `time_estimated`, `hours_unset`, `no_movement`), `run` FK. Unique (`branchcode`, `storecode`, `itemcode`,
    `started_at`).
  - `ItemAvailabilityDay`: `branch`, `item`, `day`, `abc_class`, `open_minutes`, `out_minutes`, `is_out`,
    `daily_rate`, `lost_units`, `lost_value`. Unique (`branch`, `item`, `day`).
- **Job.** Nightly after `stock_ledger_catchup` (03:15). Recomputes the last 7 days (the catch-up window) and
  replaces those days. Idempotent. Plus a "recompute" button (background, one at a time).
- **Pilot first:** SystemSetting `availability_branches` (CSV, default `160,<comparison>`; open question 1). Other
  branches are added by the owner.

### Step 2 — the morning list «ناقص هنا — متوفر هناك» (PG only; view-only)
New function `availability.build_daily_list(on_date)`. It runs at 08:30, after the 08:10 ledger sync, and from a
refresh button.
- **Rows:** branch × item in step-1 scope where:
  - stock + in transit is ≤ 0, or cover < `availability_list_cover_days` days (SystemSetting, default 3 from the
    card). Cover = (stock + in transit) ÷ (`monthly_avg` ÷ 30);
  - **and a source exists:**
    - HQ: whole packs in HQ real-balance stores (100, 104) ≥ 1; or
    - another branch with `_excess(stock, ceiling(rate, DEFAULT_DONOR_COVERAGE)) ≥ 1`. **Only true surplus moves**;
      the donor always keeps its own ceiling (card risk).
  - Items where `blocks_sale(item)` or a return-only flag applies are left out (rule 4).
- **Columns:** item, branch (label), stock, in transit, cover days, "out since" (open spell start, step 1), daily
  rate, best source + quantity (HQ first when it covers the need alone, as the existing owner rule), need =
  `coverage_need(rate, stock + transit, fill)` with the plan's existing fill default.
- **Model** `AvailabilityListLine`: `list_date`, `branch`, `item`, the columns above (snapshot), `status`
  (`new` / `added` / `dismissed` / `resolved`), `shortage_list` FK (null), `dismiss_reason`, `acted_by`, `acted_at`,
  `resolved_at` (the first ledger line with `newqty > 0` at that branch after `list_date`). Unique (`list_date`,
  `branch`, `item`). A line still out the next morning is carried on the new day's list with its original
  "out since".
- **Who sees what:**
  - branch salespeople: their own branch's lines, read-only (`core/branch_scope.py`);
  - the store specialists: the network list, all branches (open question 3 names the role).

### Step 3 — "add to transfer" (reuses the P-33 path; no new writer)
- The network list gets a select grid (`useGridKeyboard`: ↑↓ Space Enter Ctrl+A). «إضافة للتحويل» on the selected
  lines:
  1. creates or extends **one `ShortageList` per branch per day** with `source='availability'` and confirmed
     `ShortageItem`s (`quantity_needed` = the line's need, in packs);
  2. opens the existing P-33 plan (`transfer-plan`, which re-reads live stock) in the existing `PlanView`; the user
     creates the legs there.
- Lines become `added`, with the shortage list linked. A second click on the same line → "already added".
- Double moves are blocked by the existing `IsrPush` constraint (`origin_shortage_list, origin_donor, kind`). SOFTECH
  is written only by the existing ISR tab approve → push, with its guards.
- **HQ-sourced lines** (the most common case in the card's example) need a decision (open question 4):
  - (a) the specialist adds them to the next daily HQ → branch route ISR by hand (no code; the list shows "from HQ");
  - (b) `create_request_transfers` also makes one HQ → branch leg (`origin_donor='100'`) for the plan's `from_hq`
    part. This changes P-33 behaviour and a live ISR staging path, so stop-and-ask.
- «تجاهل» needs a reason (e.g. reserved for a customer, damaged, already called). Every add / dismiss writes
  `AuditLog` (who, what, when, why, before/after).

### API (`apps/stock_audit/urls.py`, new `availability_views.py`)

| Endpoint | Method | Permission |
|---|---|---|
| `/api/stock-audit/availability/summary/?branch=&from=&to=` | GET | branch-scoped (own branch) or all-branch |
| `/api/stock-audit/availability/spells/?branch=&item=&from=&to=` | GET | same |
| `/api/stock-audit/availability/compare/?branches=&days=` | GET | all-branch (purchasing / store specialists) |
| `/api/stock-audit/availability/list/?date=&branch=` | GET | own branch; network = all-branch role |
| `/api/stock-audit/availability/list/add-to-transfer/` | POST `{line_ids}` | `can_supply_write` + all-branch |
| `/api/stock-audit/availability/list/<id>/dismiss/` | POST `{reason}` | `can_supply_write` + all-branch |
| `/api/stock-audit/availability/recompute/` | POST (background) | `can_supply_write`; one at a time |
| `/api/stock-audit/availability/export/?sheet=` | GET (xlsx) | as the sheet's GET |

All checks are server-side. A branch user asking for another branch → 403.

### Screen
New page `/availability` «التوفر»; inner tabs with `useHelpTab(tab)`:
- **قائمة اليوم** — the morning list (network or own branch).
- **التوفر المقاس** — per branch: % of A-item days in stock, out minutes, top items by lost value; drill to spells.
- **المقاس مقابل التقدير** — measured vs engine estimate, branch 160 vs the comparison branch, 90 days.
- `DataFreshnessBar domains={['stock','stock_audit','availability']}`. New freshness domain `availability` (source
  `AvailabilityRun`, cadence 1440). The engine run date is shown as text.
- Refresh / recompute with `ProgressBar`.
- Branch names via `useBranchLabels` / `BL` on screen and in Excel; never a bare branch code. «سيرفر» wording.
- No popup for common actions; the plan opens in place (rule 11).

### Help
`apps/help/content/stock_audit.py`: new screen `stock_audit.availability`, route `['/availability']`, one section
per inner tab and per list status (`new`, `added`, `dismissed`, `resolved`), Arabic + English, `updated`. Cross-reference
in `apps/help/content/shortage.py` (`/shortage`: lists with source «التوفر») and bump its `updated`.

### Files
- Step 0: `apps/stock_audit/management/commands/verify_ledger_newqty.py`.
- Steps 1–2: `apps/stock_audit/availability.py`, `apps/stock_audit/models.py`, `apps/stock_audit/availability_views.py`,
  `apps/stock_audit/urls.py`, `apps/sync/tasks.py` (two jobs), `apps/sync/freshness.py` (domain).
- Step 3: `apps/shortage` (create a list with `source='availability'`; no model change), the frontend plan reuse.
- Frontend: `frontend/src/pages/AvailabilityPage.jsx`, route + nav, `frontend/src/api/client.js`.
- **Migration:** `stock_audit/0005_availability` (new tables only). SystemSettings seeded in the same migration.

## 3. Acceptance criteria

- **Step 0** report exists for branch 160, with the pass rule result. The owner signs off before step 1 starts.
- Spell maths on fixtures:
  - sale to 0 at 18:40, receipt at 11:00 the next day, branch open 09:00–24:00 → 5 h 20 min + 2 h = 440 open
    minutes out (test);
  - open spell at run time is counted to "now" and stays open;
  - state carried from before the window;
  - a line at another store of the same branch does not end the spell (when step 0 shows per-store `newqty`);
  - null `trans_time` → `time_estimated`.
- Recompute of the same days gives identical rows (idempotent test).
- Items not A/B, below the rate floor, sale-stopped, or in stores 110/102/103/105 never appear (tests).
- The donor quantity on a list line never exceeds `_excess` at `DEFAULT_DONOR_COVERAGE` (test).
- "Add to transfer" twice → one shortage list per branch per day, and no second leg (test against the P-33
  constraint).
- A branch user sees only their branch; POST by a user without `can_supply_write` → 403; each add / dismiss → 1
  audit row (tests).
- No SOFTECH connection is opened by steps 1–2 (mocked connector asserts no call).
- `test_help.py` passes.

**Tests**

| File | Proves |
|---|---|
| `apps/tests/test_availability_spells.py` | spell start/end, open hours, carried state, store split, flags, idempotent recompute, day rule, lost units |
| `apps/tests/test_availability_list.py` | scope filters, cover threshold, HQ-first and donor surplus, safety exclusions, carry-over, resolved_at |
| `apps/tests/test_availability_api.py` | branch scope, permissions, add-to-transfer → ShortageList + P-33 guard, dismiss reason, audit, export |
| `apps/tests/test_stock_audit_ledger.py`, `test_shortage_transfers.py` | still pass |
| `apps/tests/test_help.py` | new route and tabs have help |

## 4. Measurement

- **Measured A-item availability % per branch** (% of A item-days in stock). Baseline: the first 4 weeks; branch 160
  vs the comparison branch.
- Stock-out days on A items, and measured lost value per 30 days. This replaces the ≈390k/30d estimate as the
  reported figure once step 0 passes. The margin figure follows the P-35 basis.
- Measured vs estimated out-days per pair (calibration error) for the engine.
- List lines per day; share added / dismissed / left; time from list date to `resolved_at`.
- Phone / WhatsApp escalations for non-urgent cases: to measure (no source today; open question 6).

## Out of scope

- Any SOFTECH write. ISR legs reach SOFTECH only through the existing approve → push by a person.
- Changing `lost_sales_engine.py` or the engine's `stockout_days_30d` (measured figures are reported beside it).
- HQ's own stock-outs (a purchasing matter, P-34).
- Real-time alerts. The list is a morning list; the ledger is 2-hourly.
- `pos_cancel` as lost demand, and the P-47 capture.

## Open questions / owner inputs

1. **Comparison branch** for the pilot: which branch beside 160?
2. **`newqty` meaning** (step 0): per store or per branch; strips (fractional) — is 0 < `newqty` < 1 "in stock"?
   Can `newqty` be negative?
3. **Store specialists in the system:** which app role or SOFTECH group? Is `can_supply_write` (admin, purchasing,
   supply groups) the right gate for "add to transfer"?
4. **HQ-sourced lines:** (a) by hand into the daily route ISR, or (b) an HQ → branch leg from the list (P-33
   change)?
5. **Thresholds:** cover days (3, from the card); donor keeps 1 month (existing default); day-out share (0.5
   proposed); step-0 pass rule (19/20 and 95%).
6. **Branch hours:** are `BranchSettings` hours filled for 160 and the comparison branch? (read-only check)
7. **"Top sellers" at a branch:** ABC is network level. Keep network A/B + the branch rate floor, or rank per
   branch? An item that was out for months has a low branch rate and may drop out of scope.
8. **Branch salespeople:** view only (card), or may they raise a request from their list (into their branch's
   shortage list)?
9. **Escalation baseline:** is there any count of non-urgent phone / WhatsApp stock calls to compare against?

## Stop-and-ask

- Any SOFTECH write, or any change to the ISR writer, `isr_guards` or the P-33 transfer behaviour (option 4b).
- Any new SOFTECH read. None is planned: steps 0–2 read PG mirrors only; step 3 reuses the existing bounded live
  `stkbal` read of the P-33 plan. If step 0 shows the mirror cannot answer (e.g. a store missing from the ledger), a
  new read must be `docdate`-bounded (`stktrans_60`; `trans_time` is unindexed and times out). Confirm first.
- Using measured spells to change the engine's stock-out estimate, the ISR quantities or the coverage writer
  (P-34). That feeds ordering and SOFTECH `maxnowqty`.
- Building step 1 if step 0 fails.
