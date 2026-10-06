# 18 — Narrative Insights & Automated Audit Reporting

**Status:** ✅ BUILT (2026-07-30) — bilingual (AR/EN) rule-based narrative reports for
day/week/month, deliverable to WhatsApp + an in-app page. Analytics-side; **no forecasting,
no SOFTECH writes.**

## What it is
A scheduled engine scans the PG mirror for a period, checks each **owner-tuned rule** against
thresholds, emits **auditable findings**, and renders a **deterministic bilingual narrative**.
Built for non-technical directors (large, clean, plain-language). Numbers come from
`forecasting.KpiResolver` / grouped queries — never invented — so they agree with the KPI board.

## App: `apps/insights`
- **Models:** `InsightRule` (owner-editable: threshold/enabled/severity/periods), `InsightRun`
  (period + rendered `narrative_ar`/`narrative_en` + audit), `InsightFinding` (structured
  per-fact record), `InsightRecipient` (WhatsApp numbers, per-branch or chain).
- **`rules.py`** — rule catalog (efficient GROUPED queries; add a rule = 1 function + `RULES` entry).
- **`engine.py`** — `InsightEngine.run(period_type, ref_date)` → run + findings + narrative;
  `render` (chain) / `render_for_branch` (per-branch); rolling windows (day=1, week=7, month=30),
  prev-period = equal window before.
- **Command** `generate_insights --period day|week|month [--date] [--send] [--print] [--lang]`.
- **API** `/api/insights/reports/` (+ `generate/`), `/api/insights/rules/`. **UI** `/insights`
  (report list · AR/EN toggle · copy-for-WhatsApp · findings).

### Underperformer (bottom-N) rankings (added 2026-08-29)
Every rankable KPI now emits a **ranked bottom-N laggard board** alongside its top-N leaderboard,
so directors see who needs attention, not only who's winning. Same rule, same population, same
pass — top and bottom are two slices of one materialised data list, so **no extra queries**.
- **Helpers** `_ranking` / `_basket_rank_finding` / `_pct_rank_finding` take `bottom=True`
  (sort ascending, take `ctx.bottom_n`, worst first) and emit a `category='bottom'`,
  `severity='warning'` finding instead of `highlight`/`info`.
- **Covered rules** (both branch & salesperson where applicable): `branch_rankings`,
  `salesperson_rankings`, `profit_rankings` (profit + margin%), `segment_rankings`,
  `basket_ranking`, `rank_salespeople`, `rank_cosmetics`, `rank_delivery`, and `customer_mix`
  (**new customers only** — a low returning/bulk count is not inherently "bad", so those are
  **not** inverted). `bulk_cash_ranking` is intentionally **not** inverted for the same reason.
- **Fairness guards:** a bottom board fires only when ≥ `ctx.bottom_min_pop` members are ranked
  (non-zero) — so a ~5-branch chain never gets a meaningless "bottom 5 of 5" (salespeople, many
  reps, do). Zero/blank values are excluded (a zero = didn't participate).
- **Per-member callout:** `branch_standings` and `salesperson_profile` append a
  `⚠️ ضمن الأدنى N / In the bottom N` clause (via `_bottom_flag`) so the underperformance is
  named in that member's OWN branch/rep report. It is **value-based and tie-aware** — a member
  merely placed last by an unstable sort of tied values is never flagged (requires a strictly
  better performer and a tie block that doesn't straddle the boundary).
- **Render:** `engine.render` adds a dedicated `🔻 الأدنى أداءً / Bottom performers` section
  (after 🏆 highlights); bottom findings are kept out of the "Top items to act on" attention
  list and the compact findings summary.
- **Owner tunables** (SystemSetting): `insights_bottom_n` (default 5), `insights_bottom_min_population`
  (default 8, forced > `bottom_n`).

### Daily "real working day" gate — partial/off-day reps set aside (added 2026-08-31)
Fixes the misleading case where a rep who worked a late shift crossing midnight, was off the next
day, or worked a partial day lands at the **bottom of the DAILY report** on time-correct but
misleading data. `Ctx._compute_partial_day_reps()` (day period only) builds `partial_day_reps` — **PRESENCE
decides set-aside**: a rep is set aside only when the presence gate fails — fewer than `min_active`
transactions, OR active across fewer than `daily_min_hours` (default 3) distinct `trans_time` hours
(**only when hour data exists** — a null/absent `trans_time`, `hrs==0`, never sets aside a real rep;
falls back to txn count). A rep who was **present all day but simply sold little is NOT set aside** —
that is real underperformance and STAYS in the bottom list. The **extreme-drop** signal (today's
sales < `daily_offday_ratio` (default 0.25) × their own trailing daily average over
`daily_trailing_days`, default 28 active days) does **not** set anyone aside on its own — it only
**labels** an already-set-aside (weakly-present) rep as *'likely off'* (`drop`) vs a plain
short/night shift (`partial`).

Set-aside reps are excluded from all daily rep **bottom rankings + underperformer flags**
(`salesperson_rankings`, `profit_rankings`, `segment_rankings`, `basket_ranking`,
`cash_exbulk_ranking`, `rank_salespeople`, the `salesperson_profile` bottom-flag, plus
`salesperson_below_avg` / `salesperson_no_beauty`) — **not** from totals, and **not** weekly/monthly
(`partial_day_reps` is empty there, so the filters are no-ops). `rule_daily_offday_note` (day only)
names them with the reason (partial/night shift vs extreme drop) in the 🔻 section, so a partial/off
day is **confirmed, not hidden**. Note: `invoice_date` is date-only — time-of-day lives in
`trans_time`. Tunables: `insights_daily_min_active_hours`, `insights_daily_offday_ratio`,
`insights_daily_trailing_days`.

### Data-freshness / completeness assurance (added 2026-09-01)
Every report header states whether SOFTECH data is fully collected for the period. `rules.data_freshness(start,
end, domain)` returns the mirror `data_through` per source (sales = `max(PurchaseHistory.invoice_date)`,
purchasing = `max(PurchaseLine.doc_date)`), the last successful `SyncRun` time (advisory — may be blank if the
tiered fast/slow sync doesn't log it), whether the period `end` is `covered`, `gap_days` short, **AND — the
important part — INTERIOR gaps**: `empty_days` (days inside `[start,end]` with ZERO sale invoices = definite
sync gaps) and `low_days` (< 30% of the period median = likely partial sync), via `_period_sales_gaps`.
`complete` = covered AND no interior gaps. **This was added after a real case:** a full-month report reconciled
exactly with the resolver but was ~10% below SOFTECH because Aug 27 was entirely missing and Aug 19 partial in
the mirror — a stale-tail (max-date) check can't see interior holes, only a per-day density check can.
Coverage/completeness is judged on the ACTUAL data, not the sync log, so it's reliable. Interior-gap detection
is SALES-only (purchasing is legitimately lumpy). Remedy surfaced: `backfill_sales_history` those days.
- `InsightEngine.freshness_header(end, domain, lang)` prepends a header line: `🕒 البيانات مكتملة
  حتى …` when covered, or `⚠️ بيانات غير مكتملة … (ناقص N يوم) — أعِد المزامنة (sync_erp /
  run_procurement_engine)` when the period isn't fully synced. On the chain board it always shows;
  on per-branch/per-rep reports it shows only the warning.
- **Live endpoint** `GET /api/insights/reports/freshness/?domain=&start=&end=` returns the same
  data (incl. `empty_days`/`low_days`/`complete`) so the UI can confirm freshness BEFORE generating;
  `/insights` renders a green (complete) / amber (gaps: N days short + missing/partial days listed) /
  red (last sync failed) bar under the header.
- **Backfill from the UI** (like the sync page): `POST /api/insights/reports/backfill/`
  `{domain,start,end}` (admin/supervisor) kicks off a BACKGROUND job — SALES →
  `backfill_sales_history --start --end` (owns its `SyncRun`), PURCHASING → `run_procurement_engine
  --days N` (wrapped in a `SyncRun`) — and returns 202. It guards against an in-flight run and
  surfaces on `GET /api/sync/status/`. The amber gap bar shows a **🔄 تعبئة الأيام الناقصة** button
  that triggers it, polls `sync/status` every 4s, and auto-refreshes freshness + reports when done.

### Purchasing KPI expansion (added 2026-08-30)
Richer HQ + all-branch purchasing remarks on `procurement.PurchaseLine` (domain=`purchasing`,
reachable at **المشتريات والتموين → scope فرع → المخزن الرئيسي** for HQ detail). All read-only.
- `hq_purchase_summary` **enriched** into an HQ at-a-glance headline: net value + distinct items
  + suppliers + **invoice count & avg invoice** + returns value/rate + FOC + trend vs prev. HQ
  central buying is **lumpy** (deliveries every few days), so on a no-delivery period it now emits
  a **zero-state note** ("no central purchases this period — last central delivery {date}") instead
  of returning nothing — this keeps **HQ always selectable in the purchasing branch scope** (it
  used to vanish from the dropdown on HQ-zero days while branches, which buy locally most days,
  stayed). Regenerate the report for stored runs to pick this up.
- `purchase_supplier_category` — purchase **value + share% + distinct items per supplier
  category** (= the "purchasing channel": official distributor / manufacturer / small warehouse /
  patient-Rx / internal transfer / service). Chain (board) + HQ + each branch (فرع report).
- `purchase_invoice_count` — distinct invoices + avg invoice value; chain (board) + per branch
  (incl HQ). Invoice = distinct (branch, supplier, doc_number).
- `purchase_input_vat` — input VAT (`vat_value`) + tax-inclusive cost; chain + HQ.
- `supplier_expiry_returns` — expiry returns-to-supplier value + share (`return_type='expiry'`);
  chain + per branch (week/month).
- `buyer_ranking` — top/bottom HQ buyers by net purchase value (reuses `_ranking` bottom mode).
- **FOC valuation fix (2026-09-01):** بضائع مجانية/FOC value was computed as `cost_price ×
  raw_qty` — but on an `is_foc` row `raw_qty` = the **PAID** units and `bonus_qty` = the **FREE**
  units (see `procurement/engine.py`: paid line carries raw_qty/value, free units captured in
  `bonus_qty`). It now correctly uses `cost_price × bonus_qty` (free units × cost) for value and
  `Σ bonus_qty` for units, in `hq_purchase_summary`, `foc_captured`, `purchase_overview`. On HQ Aug
  MTD this dropped FOC from an inflated **450,817 / 4,748u** to the correct **63,761 EGP / 762 free
  units** (7.1× overstatement). Audit tool: `python manage.py foc_audit --branch 100 --month
  2026-08` prints correct-vs-old value, retail view (`public_price × bonus_qty`), inflation factor,
  and a per-item/-supplier breakdown to reconcile the figure line by line.
- **Gift items excluded from stock rules (2026-09-01):** `excluded_item_ids` now also covers
  customer-gift items — SystemSetting `analytics_excluded_medicine_types` (default `60` = هدايا
  العملاء / client gifts) plus keywords now defaulting to `COUPON,كوبون,هدايا,هدية`. Applied to
  `dead_stock` + `stockout_fastmovers` (and the existing item-level sales rules), so gift items no
  longer clutter stock/dead-stock findings.
- **Excluded suppliers:** `_purchases()` (and `supplier_scorecard`) drop supplier codes in
  SystemSetting `analytics_excluded_supplier_codes` (default `1268` = «هدايا الادارة لخدمة العملاء»,
  the management customer-gift/coupon account — coupons bought to be dispensed to PIC customers, not
  real procurement). Applied at the `_purchases()` base so **every** purchasing value/count/FOC/
  supplier-category/ranking omits them. (NB: the FOC/بضائع مجانية figure is REAL supplier bonus
  goods — top contributors PHARMA OVER SEAS / RAMCO / PARKVILLE — not coupons; excluding 1268 barely
  moves it because 1268's FOC is ~0.) Helper `_excluded_supplier_codes()`.
- Helpers: `_inv_count`, `_cat_breakdown`, `_cat_lbl`, `_purchase_branch_codes`. `Ctx` gained
  `all_branch_by_code` + `branch_name(code, lang)` so HQ (code 100) is **labelled**, not shown as
  raw "100" (fixed `patient_repurchase_volume`). All 5 codes added to `_PURCHASING_CODES`.
- **GOTCHA hit & fixed:** `values_list('branch_code').distinct()` iterated (not counted) returned
  a code once per date because the model's `-doc_date` Meta ordering is silently added to DISTINCT
  → use `.order_by()` before `.distinct()` (same class of bug as the InsightFinding one). `.count()`
  is unaffected (it strips ordering).

### Ex-bulk cash-sales rankings (added 2026-08-30)
`cash_exbulk_ranking` (sales, day/week/month) — top AND bottom leaderboards of **cash sales value**
(walk-in + delivery + عميل دائم = `ctx.cash_channels`), **net of returns**, **excluding bulk
invoices** — one SEPARATE remark per floor, for **branches and salespeople**. Stripping big one-off
invoices makes everyday selling comparable across reps/branches. Floors are dedicated & owner-tunable
(SystemSetting `insights_cash_exbulk_floors`, default `5000,10000`) so they don't move with the
basket/bulk-cash floors. Exclusion = `total_amount < floor`. Helper `_net_cash_exbulk_by(ctx, thr,
group_field)`. Reuses the shared `_ranking` bottom mode + `bottom_min_pop` guard (so branch bottoms
self-suppress in a small-branch chain). Emits up to 8 findings (2 floors × {branch,rep} × {top,bottom}).

## Rule catalog (19 rules) — extensible. Data sources in brackets.
**Sales & coverage** [`customers.PurchaseHistory(+Line)`]
| code | category | fires when (threshold) |
|---|---|---|
| `branch_vs_prev` | comparison | branch net sales down ≥ X% vs previous period (25) |
| `branch_zero_delivery` | coverage | zero delivery while normally active |
| `branch_zero_callcenter` | coverage | zero CC-agent orders while normally active |
| `branch_no_new_customer` | coverage | no first-time PIC registered |
| `salesperson_no_beauty` | mix | active rep (≥ X EGP) sold no beauty (5000) |
| `salesperson_below_avg` | volume | rep sales < X% of trailing-4-period avg (50%) |
| `high_discount` | discount | line discount ≥ X% tax-inclusive (30) |
| `bulk_sale` | discount | invoice ≥ X EGP (20000) |
| `top_branch` | highlight | best-growing branch vs previous period |

**Leakage / performance** [`PurchaseHistory(+Line)`]
| `below_cost_sale` | discount | line sold below cost by ≥ X EGP (100) — margin leak |
| `branch_high_returns` | volume | branch returns/sales ≥ X% (8) |
| `branch_margin_drop` | comparison | gross-margin % fell ≥ X points vs prev (3) |
| `salesperson_over_discount` | discount | rep avg discount % ≥ cap (12) |

**Purchasing** [`procurement.PurchaseLine`, HQ=branch 100]
| `hq_purchase_summary` | highlight | HQ value purchased + distinct item codes |
| `purchase_category_mix` | comparison | split by supplier category (official distributor / manufacturer / small warehouse / patient-Rx / internal) + small-warehouse-dependency warning ≥ X% (30) |
| `supplier_return_spike` | discount | return-to-supplier value ≥ X EGP (20000) |

**Stock** [`stockcount.StockCountSession`]
| `stock_variance` | coverage | a count with ≥ X deficit/surplus items (15) — shrinkage |

**Inter-branch cooperation** [`transfers.TransferRequest`]
| `branch_cooperation` | highlight | transfer count + top helper (supplying) branch |
| `branch_isolation` | volume | operational branch with no transfer activity |

> **Data freshness:** purchasing rules depend on `procurement.PurchaseLine` staying current
> (run `run_procurement_engine` daily). Sales/transfers/stock read live mirrors.

## Delivery
Deterministic templates (audit-grade, free, consistent). WhatsApp Cloud API sends to **individual
numbers** (`InsightRecipient`) — it **cannot post to groups**; recipients forward to their branch
group, and the `/insights` page has a one-tap **copy** for that. Branch recipients get a
branch-filtered narrative; chain recipients get the full board report.

## Scheduling (recommended, Cairo)
`generate_insights --period day --send` at 07:00; `--period week --send` Sun 08:00;
`--period month --send` on the 1st 08:00 (Windows Task Scheduler / APScheduler).

## Extending
Add a scenario = a rule function returning finding dicts + a `RULES` registry entry (defaults
seed a config row; owner tunes threshold in admin/UI). Reuse `KpiResolver` for any metric so
numbers stay consistent across board / targets / insights.
