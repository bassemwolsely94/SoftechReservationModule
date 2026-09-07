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
