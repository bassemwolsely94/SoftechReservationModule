# 16 — Branch KPI Forecasting & Target Engine

**Status:** ✅ PHASES 1–6 BUILT (2026-07-29) — actuals, targets, board, engine, backtest, call-center & salesperson/category scopes live
- **Phase 6 (salesperson & category scopes):** `KpiResolver.resolve` gained `category_id`
  (line-based, a category's own sales) alongside `softech_user` (salesperson, header-based);
  `SalesTarget.actual_value()` routes all three scopes. `ForecastScenario.scope_type`
  (branch/salesperson/category) + `ForecastResult.scope_key`/`scope_label` (migration 0007);
  `ForecastEngine` generalized to iterate scope members (`_members`, cap 60 by recent sales) and
  `commit` upserts scope-appropriate `SalesTarget`s. UI: scope selector + per-member breakdown on
  `/forecast-scenarios`. Validated on real data: salesperson (56 reps) + category (60 cats) generate
  → commit → attainment; chain totals reconcile to the branch decomposition (~4.2M). NOTE: existing
  `apps/analytics` already covers salesperson/category/item *analytics* (by_employee/by_category/
  inventory) — Phase 6 adds *targets+forecast* at those grains, not new dashboards. Perf: non-branch
  generate does per-member resolver queries (~1–3 min for 60 members); optimise with batched
  aggregation if needed.
- **Phase 5 (call center):** decoded from the owner's Call-Center-KPIs workbook + CDR CSVs.
  **Sales/profit/beauty/orders** = `PurchaseHistory` where `softech_user ∈ {62,63,64}` (all
  branches; validated Jun sales 833,733 == workbook). **Call count** = Issabel CDR: ANSWERED,
  `src ∈ agent extensions {10,12,15}`, dst→11-digit mobile (strip 2-digit GoIP prefix), per-day
  distinct summed (validated May 1,905 ≈ sheet 1,887). `CallCenterConfig` (editable agent codes +
  extensions), `KpiResolver.compute_call_center_month`, `apps/forecasting/callcount.py` (shared
  CSV+DB logic), `config/issabel.py` (pymysql CDR connector, `.env`-driven), command
  `build_call_center_rollups` (`--cdr-csv` or live). CC stored under a dedicated non-operational
  "Call Center" branch (excluded from branch totals); board shows it as a separate 📞 section.
  **Penny-exact net (2026-07-29):** SOFTECH doesn't stamp the CC agent on returns, but stktrans
  returns carry `r_docnumber` (the original SALE's number). `apps/forecasting/cc_softech.py`
  (`cc_returns_from_softech`) sums doc-30 returns whose `r_docnumber` → a doc-115 sale by a CC agent
  (EXISTS, no join fan-out) for amount + profit; `build_call_center_rollups` subtracts them from
  gross → NET. Jun-2026 net 827,987 vs workbook 828,628 (0.08%), profit 141,141 vs 141,298 (0.11%).
  Residual is the sheet's exact filter (returns 5,746 vs 5,105).
- **Phase 4 (backtest):** models `BacktestRun` / `BacktestResult` (migration forecasting/0005),
  `apps/forecasting/backtest.py` (`BacktestService`) replays Model A vs B across testable months
  (base=M-12, LM=M-1, PM=M-2, actual=M) at chain level, scores MAPE/WAPE/bias/RMSE, picks the
  lowest-WAPE winner per metric. API `forecasting/backtest/` (+ `run/`); UI backtest panel on
  `/forecast-scenarios`. **Real 24-mo result (2025-08→2026-07): Model B wins ALL 5 metrics** —
  WAPE beauty 5.6% · cash+delivery 6.3% · gross_profit 5.9% · customer_count 10.8% · credit 10.8%
  (vs Model A 9.8/10.3/10.7/23.0/35.4%). B tracks recent momentum → adapts to growth/decline;
  A's fixed goal-growth badly under-forecasts fast-growing credit (−37% bias).
- **Phase 3 (forecast engine):** models `ForecastScenario` / `ForecastFactor` /
  `ForecastResult` (migration forecasting/0004), `apps/forecasting/engine.py`
  (`ForecastEngine`: Model A goal-growth, Model B weighted LM/PM/YoY blend, avg;
  branch-share; generate→commit→`SalesTarget`). API `forecasting/scenarios/` (+ `factors/`,
  `generate/`, `results/`, `commit/`). Frontend `ForecastScenarioPage.jsx` at
  `/forecast-scenarios`. Engine math unit-tested (12 tests green).
- **Phase 3.5 (historical backfill):** ✅ DONE (2026-07-29). SOFTECH backfill chosen.
  `backfill_sales_history` (month-by-month windowed pull + rollup rebuild) +
  `QUERY_CUSTOMER_SALES_LINES_WINDOW`. Loaded **24 months** (2024-08 → 2026-07, ~535k invoices).
  Fixed a tz-boundary bug in `sync_sales`: `docdate`→`inv_id` date shifted across the UTC
  boundary so the same invoice got two ids (`…-0530`/`…-0531`) and the upsert doubled every
  re-synced month — now localises tz-aware docdate before formatting + merges same-id rows
  within a batch (also hardens the production 90-day sync). Truncated + reloaded clean:
  May 2026 = 22,449 invoices, **0 duplicates**, chain cash+delivery 4,235,826
  (= 4,229,791 retail + 6,035 HQ). Real June-2026 forecast within 5–10% on money metrics;
  customer_count over-forecasts (declining traffic → needs a negative growth factor).
- **Phase 1 (actuals & config):** models `ChannelBucketMap` / `BeautyClassRule` /
  `KpiActualRollup` (migration forecasting/0003), resolver `apps/forecasting/kpi.py`
  (`KpiResolver`), commands `seed_kpi_config` + `build_kpi_rollups`, admin, tests
  `apps/tests/test_kpi_rollup.py`. **Validated vs تحقيق مايو 2026**: chain
  cash+delivery/credit reproduce to −0.0% (Δ ≈ 2 EGP on 4.2M), customers −0.2%,
  gross-profit +2.2% (known residual — Excel معامل الربحية nets a discount factor, TBD).
- **Phase 2 (targets & board):** `KpiResolver` generalised to any branch-set × date
  range (+ optional salesperson); `incentives.SalesTarget` metrics widened to the KPI
  set (`cash_delivery`/`cash`/`delivery`/`credit`/`gross_profit`/`beauty`/`customer_count`;
  migration incentives/0010) with `actual_value()` routed through the resolver
  (net_revenue/orders unchanged). KPI board API `GET /api/forecasting/kpi-board/?year=&month=`
  (actuals from rollups + matched targets + pace; operational branches only). Frontend
  `KpiBoardPage.jsx` at `/kpi-board` (Excel-style branch×metric matrix, month picker,
  pace colours) + nav under التحليلات. Tests: `SalesTargetKpiMetricTests` + board view.
**Owner initiative:** replace the manual monthly Excel target/achievement workbooks
(`تارجت شهر …` / `تحقيق شهر …`) and the `ElRezeiky_Forecasting_System_v2.xlsx`
skeleton with a first-class, factor-driven forecasting + target engine inside the
platform.

> **Golden rule reminder:** this **extends** `incentives.SalesTarget` and adds a
> branch-KPI layer to `apps/forecasting`. It does **not** create a new targets model
> and does **not** touch the item-demand forecaster (`ForecastService`), which is a
> different altitude (per-item units → purchasing).

---

## 1. Why this exists

Today branch targets are produced **by hand in Excel every month**:

- **`تارجت شهر … .xlsx` / `تحقيق شهر …`** — the monthly target/achievement template.
  Per branch (130 علياء · 140 بليغ · 150 عين شمس · 160 باب الحديد · 170 محسن) it tracks
  cash + delivery + عميل دائم, credit (آجل), gross-profit factor (معامل الربحية),
  customer count, cosmetics/others, plus a **Call Center** unit
  (المبيعات · الربحية · التجميل · عدد العملاء · **عدد المكالمات**). Daily pacing column
  «المطلوب خلال المدة» = monthly target ÷ days-in-month.
- **`ElRezeiky_Sept2026_Forecast_Targets.xlsx`** — the **Model A** target-setting method
  (base × growth ÷ threshold, split to branches by historical share).
- **`ElRezeiky_Forecasting_System_v2.xlsx`** — a **Model B** parameter skeleton
  (LM/PM/YoY weighted blend + Calendar working-days + seasonality). Its
  `Forecast_Engine` / `Forecast_Accuracy` sheets are **empty** — the blend was
  parameterised but never wired, so we implement it cleanly rather than port formulas.

Everything these workbooks compute is **derivable from the existing PostgreSQL mirror**
(`customers.PurchaseHistory` / `PurchaseHistoryLine` + `catalog` + `sync` reference
tables). The manual step is unnecessary.

### What already exists (reused, not rebuilt)

| Component | Role | Change |
|---|---|---|
| `incentives.SalesTarget` (+ `/targets`, `TargetsPage.jsx`) | Manual target with live `attainment()` (pct + **pace** + expected-to-date = «المطلوب خلال المدة») | **Extend**: widen metrics; keep attainment logic |
| `customers.PurchaseHistory` / `PurchaseHistoryLine` | The actuals source (`doc_code`, `sales_channel`, `sales_person_type`, `softech_user`, `softech_phcode`, line→`item→category`, `cost_at_sale`) | Read-only source |
| `sync.SoftechPersonClassif` | `(ptcode, ptclassifcode) → Arabic label` — the channel dictionary | Read-only source + seed for the bucket map |
| `catalog.Item.medicine_type` (itemmedicine) | Beauty vs medicine vs services flag | Read-only source |
| `apps/forecasting` (`SeasonalityIndex`, `ForecastRun`, `ForecastAccuracy`) | Item-demand forecaster | **Untouched**; new branch-KPI models live alongside |
| `apps/pbx` (Issabel CDR) | Call-center calls (عدد المكالمات) | Source for call-count metric (mapping TBD) |

---

## 2. Grounded metric dictionary

All figures net of returns (`doc_code='30'`) unless noted. Verified against live data
2026-07-29.

| Metric | Key | Definition (PurchaseHistory `PH` / `PHLine`) |
|---|---|---|
| Cash نقدى | `cash` | `PH doc=115` where channel bucket = **cash** (see §3), − returns |
| Delivery توصيل | `delivery` | subset of cash: channel `90` عميل Delivery |
| Credit آجل | `credit` | channel bucket = **credit** |
| Insurance تأمين | `insurance` | channel bucket = **insurance** (`15`); usually not targeted |
| Beauty تجميل | `beauty` | `PHLine` where `item.medicine_type ∈ {50 Cosmetics, 20 Others}` (configurable set) |
| Net revenue | `net_revenue` | all buckets combined (existing behaviour) |
| Gross profit معامل الربحية | `gross_profit` | `Σ(line_total − quantity × cost_at_sale)` |
| Customers عدد العملاء | `customer_count` | `COUNT(DISTINCT softech_phcode)` |
| Orders | `order_count` | `COUNT(PH doc=115)` |
| Call-center sales | `cc_sales` | `PH` where `softech_user ∈ {agent codes}` (⏳ codes TBD) |
| Call-center profit | `cc_profit` | gross profit of those PH lines |
| Calls المكالمات | `call_count` | Issabel CDR outgoing calls for agent set (⏳ mapping TBD) |

**Beauty excludes**: `10` Medicine, `70` Services خدمات, `40` Veterinary, `60` gifts.

---

## 3. Channel → bucket mapping (config-driven — business decision)

`PurchaseHistory.sales_channel` = `ptclassifcode`; it repeats across `ptcode`s, so a
bucket is keyed by the **pair** `(sales_person_type, sales_channel)`.

**Decision (owner):** every code is mapped **explicitly in an editable config table**
(`ChannelBucketMap`), not hard-coded. Seeded from live `ptcode=10` (customers) with
these defaults, then owner-adjustable in the UI:

| pt | ch | Label | Default bucket | Live doc-115 revenue |
|----|----|-------|----------------|----------------------|
| 10 | 91 | عميل نقدى | `cash` | 10.2M |
| 10 | 90 | عميل Delivery | `cash` (+`delivery` tag) | 4.2M |
| 10 | 30 | عميل دائم | `cash` | 0.81M |
| 10 | 11 | موظفيين شركة الرزيقي | `cash` | 0.16M |
| 10 | 12 | إيصال إلكترونى بالبطاقة | `cash` | 0.05M |
| 10 | 10 | تعاقدات / آجل | `credit` | 11.2M |
| 10 | 33 | تعاقد - سداد آجل - خصم يدوي | `credit` | — |
| 10 | 17 | تعويضات الشركات | `credit` (owner to confirm) | ~0 |
| 10 | 31 | مقاصات | `credit` (owner to confirm) | — |
| 10 | 15 | تأمين صحي | `insurance` | — |
| 10 | 16 | تبرعات | `exclude` (owner) | 0.35M |
| 10 | 99 | Vip | owner to map | — |

Buckets: `cash · credit · insurance · exclude` (extensible). A single management command
seeds/refreshes the table from `SoftechPersonClassif`; unmapped codes surface in the UI
as "needs mapping" and default to `exclude` until assigned.

---

## 4. Forecast engines

Each `ForecastScenario` names a target month, a model, and a set of factors. Three models:

### Model A — Base × Growth ÷ Threshold  (the shipped method)
```
goal            = base_same_month_last_year × (1 + growth_goal[category])
target          = goal / incentive_threshold          # ÷0.90 → 90% attainment = goal
realistic_fcast = base × (1 + recent_trailing_yoy)    # info column
```

### Model B — Weighted LM/PM/YoY blend
```
blend  = w_LM·last_month + w_PM·prior_month
       + w_YoY·(same_month_last_year × (1 + benchmark_growth))     # weights sum to 1
target = blend × seasonality[month]
       × (working_days_target / working_days_base)
       × (1 + inflation + promotion_lift)
```
Default weights (per category): Cash `.50/.30/.20` · Credit `.60/.25/.15` · Beauty `.40/.20/.40`.
LM = last completed month; PM = the month before it; YoY = same month prior year.

### Model C — Average
`target = mean(A, B)` per scope. (Owner-favoured tie-breaker.)

### Branch split
Category target → branches by **historical share**
(`branch_base / category_base`, from the same base window), with per-branch override.

---

## 5. Backtest — pick the winning model

For every historical month where actuals exist, regenerate A/B/C using **only
data available before that month**, then score:

- **MAPE** = mean(|forecast − actual| / actual)
- **Bias** = mean(forecast − actual) / mean(actual)   (over/under tendency)
- **RMSE** = sqrt(mean((forecast − actual)²))

Ranked per **model × category × (branch|chain)**; the lowest-MAPE model is flagged
`is_winner`. This operationalises the owner's criterion: *the model that best reproduces
history wins and becomes the default for that scope.*

---

## 6. Schema

**Extend** `incentives.SalesTarget`:
- widen `metric` choices to the §2 dictionary;
- per-metric actual resolver (channel bucket / category / profit / distinct-customer);
- optional `scenario` FK (nullable — manual targets still work standalone).

**New in `apps/forecasting`** (branch-KPI layer):

| Model | Purpose |
|---|---|
| `ChannelBucketMap` | `(person_type, channel) → bucket` (+`label`, `is_delivery`), owner-editable (§3) |
| `BeautyClassRule` | medicine_type codes counted as beauty (default `{50,20}`), editable |
| `ForecastScenario` | one run: `month`, `model` (A/B/C), global knobs, status, created_by |
| `ForecastFactor` | adjustable knob rows, scoped global / category / branch / month: `growth_goal`, `w_lm/w_pm/w_yoy`, `seasonality`, `working_days`, `holiday_days`, `inflation`, `promotion_lift`, `incentive_threshold`, `benchmark_growth`, `branch_share_override` |
| `KpiActualRollup` | materialised monthly actuals `(branch × metric × month)` — keeps pace/backtest fast over ~3–4M rows/mo |
| `ForecastResult` | generated figure per `(scenario, scope, metric)` before commit |
| `ForecastBacktest` | per `model × scope × metric` MAPE/bias/RMSE + `is_winner` |

**Flow:** edit factors → **generate** (`ForecastResult` drafts) → **backtest** (winner) →
**commit** → creates/updates `SalesTarget` rows → existing `/targets` attainment + pace →
feeds `incentives` (the ÷threshold gate is literally the incentive rule).

---

## 7. Rollups & analytics dimensions

`KpiActualRollup` is generated by a scheduled command from `PurchaseHistory`. Because the
raw grain carries `branch`, `softech_user` (salesperson), `item→category`, and
`medicine_type`, the same rollup engine extends to the analytics the owner wants next:

- **Salesperson analytics** — `softech_user` × metric × month (targets already support
  `scope=salesperson`).
- **Item / category analytics** — `PHLine → item → category / medicine_type` × month.
- **Category-mix** — cash/credit/beauty share per branch over time (feeds Model A shares).

These reuse the rollup + factor engine; no separate pipeline.

---

## 8. Phased build plan

1. **Phase 1 — Actuals & config.** ✅ BUILT (2026-07-29). `ChannelBucketMap` +
   `BeautyClassRule` (+ `seed_kpi_config`), `KpiActualRollup` + `build_kpi_rollups`,
   `KpiResolver` per-metric resolvers, tests. Reproduces تحقيق مايو 2026 to ≈−0.0% on
   cash+delivery/credit. Validated cash={91,11,12}, delivery={90}, regular={30},
   credit={10,33}; customers = distinct phcode on {91,90}; profit = non-credit GP.
2. **Phase 2 — Targets & attainment.** ✅ BUILT (2026-07-29). `SalesTarget` metrics
   widened to the KPI set + `actual_value()` via `KpiResolver`; KPI board API
   `/api/forecasting/kpi-board/` + `KpiBoardPage.jsx` at `/kpi-board` (Excel-style
   branch×metric matrix with pace). Operational branches only; targets managed at `/targets`.
3. **Phase 3 — Forecast engine.** ✅ BUILT (2026-07-29). `ForecastScenario` /
   `ForecastFactor` / `ForecastResult`; `ForecastEngine` Models A + B + avg; branch-share;
   generate→review→commit→`SalesTarget`; `/forecast-scenarios` UI. ⚠️ needs historical
   `KpiActualRollup` backfill (Phase 3.5) to produce non-zero real forecasts.
   - **Phase 3.5 — Historical backfill.** ✅ DONE (2026-07-29). SOFTECH chosen;
     `backfill_sales_history` loaded 24 months; tz-boundary doubling bug in `sync_sales` fixed.
4. **Phase 4 — Backtest.** ✅ BUILT (2026-07-29). `BacktestRun`/`BacktestResult` +
   `BacktestService` (MAPE/WAPE/bias/RMSE, winner = lowest WAPE per metric); `forecasting/backtest/`
   API + panel on `/forecast-scenarios`. Real 24-mo run: **Model B wins all 5 metrics** (WAPE 5.6–10.8%).
5. **Phase 5 — Call center.** ✅ BUILT (2026-07-29). Agents `{62,63,64}` (sales) + extensions
   `{10,12,15}` (calls) decoded from owner files; `CallCenterConfig`, `callcount.py`,
   `config/issabel.py`, `build_call_center_rollups`; CC section on the KPI board. CC targets =
   `SalesTarget` scope=branch on the "Call Center" branch. Validated vs workbook.
6. **Phase 6 — Salesperson & category scopes.** ✅ BUILT (2026-07-29). Targets + forecast
   per salesperson & category (not new analytics — `apps/analytics` already has those dashboards).
   Resolver `category_id`/`softech_user`; `ForecastScenario.scope_type`; scope-aware commit; UI selector.

---

## 9. Open inputs from owner

- **Channel map edge codes** — confirm `17` تعويضات, `31` مقاصات, `16` تبرعات, `99` Vip
  buckets (defaults in §3; all editable regardless).
- **Call-center agent codes** — the `softech_user` set that counts as call-center sales.
- **CDR calls mapping** — how outgoing target calls are isolated from Issabel (owner will
  demo the current Excel/Power-Query filter).
- **Employees / donations** — include in a branch's cash target or exclude? (default:
  employees = cash, donations = exclude.)

---

## 10. Non-negotiables

- Read-only mirror; **no SOFTECH writes** anywhere in this module.
- Immutable committed history: a committed `SalesTarget` is auditable; regeneration
  creates a new scenario, never silently mutates a locked target.
- Arabic-first RTL UI; every metric has an Arabic label.
- All factors live in the DB and are editable — **nothing hard-coded**.

---

## 11. Extending the metric set (how to add a metric)

The module is metric-pluggable. `KpiResolver.resolve(metric, *, branch_ids, start, end,
softech_user, category_id)` is a **dispatch table**: add a metric by (1) a constant + Arabic
label in `KpiActualRollup.METRIC_LABELS`, (2) a `resolve()` branch computing it from
`_ph_qs`/`_line_qs` (which already carry the scope filters), (3) — if it should be tracked —
add it to `BOARD_METRICS` / a scenario's metric list. It then flows through rollups, board,
targets, backtest and forecast automatically. **Test-anchor** it in `test_kpi_rollup.py`.

### Extension metrics BUILT (2026-07-30) — header scopes (branch/salesperson/chain)
| Metric | Key | Definition |
|---|---|---|
| عدد الأكواد (PIC) | `pic_count` | distinct `softech_phcode` over non-exclude channels (all handled PICs) |
| عدد الفواتير | `order_count` | doc-115 transaction count (already existed) |
| فواتير الجملة | `bulk_txn_count` | doc-115 invoices with `total_amount ≥ SystemSetting('kpi_bulk_sale_threshold', 5000)` |
| فواتير متعددة الأصناف | `multi_item_txn_count` | doc-115 invoices with >1 line |
| متوسط قيمة الفاتورة | `basket_value` | net revenue ÷ transactions (avg basket value) |
| متوسط أصناف الفاتورة | `basket_units` | Σ units ÷ transactions (avg basket size) |

### Metric-catalog build (2026-07-30) — 3 phases
**P1 — discounting family (needs `stktrans` fields):** `PurchaseHistoryLine` gained
`list_price` + 4 discount-% fields (`disc_pharmacy/additional/customer/special_pct`) + `bonus_qty`
(migration customers/0017); the 3 sales sync queries + `sync_sales` now populate them (re-backfilled
24 mo). Resolver metrics: `gross_sales`, `discount_value` (list·qty − net), `discount_pct`,
`discount_freq` (% lines discounted), `discount_to_margin`, `bonus_units`. Branch-160 Jun sanity:
discount 7.98%, freq 72.5%, disc/margin 44.5%. ⚠️ `bonus_units` implausible (bonusqty ≠ free units —
verify semantics); discount arithmetic may fold tax — calibrate vs a sample invoice.
**P2 — derivable + refinements:** `UnitCountExclusion` (owner list of items excluded from `units_sold`
— syringes/delivery-fees/swabs); resolver `units_sold`, `gross_margin_pct`, `revenue_per_customer`,
`cross_category_rate`, `new_customers`. Growth service `apps/forecasting/growth.py` + `GET
/api/forecasting/growth/` — MoM · YoY · **QoQ** · **same-quarter-last-year** (period_type month|quarter).
**P3 — reward+guardrail pairs:** `MetricGuardrail` (scope, reward_metric, guardrail_metric, operator,
threshold) + `apps/forecasting/guardrails.py` `evaluate_eligibility(target)` = reward hit AND guardrails
hold. Anti-gaming gate for `apps/incentives` (reward revenue only if discount%/return-rate in bounds).

### Design notes for the next wave (before wiring more)
- **Ratio metrics don't sum.** `basket_value`/`basket_units` are averages — `RATIO_METRICS`
  flags them. Do NOT sum a ratio across members for a chain total, and do NOT forecast a ratio
  with Model A/B directly (forecast the numerator + denominator, then divide). The board/engine
  must special-case `RATIO_METRICS` when they're added to the tracked set.
- **"Per sales channel" is a NEW scope.** Current scopes: branch / salesperson / category.
  Basket/PIC/txn *per channel* means adding a `channel` scope (a `channels` filter member set) to
  `ForecastEngine._members` + `SalesTarget` — small, mirrors the salesperson scope.
- **Category variants** of the extension metrics currently return 0 (`EXTENDED_HEADER_METRICS`
  are header-only). Line-based category variants are a follow-up if needed.
- **Analytics vs targets.** `apps/analytics` is the home for *exploratory* breakdowns (it already
  has `by_employee`/`by_category`/`by_hour`, and these same primitives can back new analytics
  cards). This module (doc 16) owns *target-setting + forecasting* on the metrics. Keep new
  descriptive dashboards in `apps/analytics`, reusing `KpiResolver` so the numbers agree.
