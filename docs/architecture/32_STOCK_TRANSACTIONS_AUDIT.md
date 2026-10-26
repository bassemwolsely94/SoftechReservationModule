# 32 — Stock Transactions Audit (تدقيق حركات المخزون)

**Status:** DESIGN APPROVED (D1, D2, D3) 2026-10-26 · Phase 0 probe DONE (§14) · Phase 1 not started.
**Date:** 2026-10-26
**Replaces:** the Power Query workbook `Power Query\Stock Transations Audit\Stock Transactions Audit.xlsx`
(weekly `stktrans_*.csv` / `stkbal_*.csv` exports from `D:\Stock Transations Audit\`).
**Related:** monitoring / investigation timeline proposal (audit trail + Issabel recordings), doc 18
(narrative insights), `apps/stockcount`, `apps/audit`.

---

## 1. Goal

Run the workbook's stock checks automatically, every day, on every node, with:

- thresholds the owner can change on screen — chain-wide defaults, plus an override for any branch;
- findings that name the **branch, item, document and employee**, with an EGP value and a severity;
- a review workflow (open → reviewed / dismissed / escalated), so the same finding is not
  re-investigated every week;
- fewer false positives than the workbook (contract free packs, sale-then-return corrections,
  split-expiry lines, near-zero prices).

**Read-only against SOFTECH. No write path of any kind.** Every number comes from deterministic rules;
no AI decides anything.

---

## 2. What the workbook does today (source of truth for parity)

The M code (`Formulas/Section1.m`) joins `stktrans` with `transdoc`, `personsdata`, `items` and `users`,
then runs:

| Workbook query | Logic | Problems found |
|---|---|---|
| Sales Below Cost | `doccode=115 and transprice < newcostprice` | Contract free packs (e.g. «FREE PACKS NOVARTIS», 0.17 EGP vs 1,211 cost) show up as −99.99% losses; no EGP floor |
| 10- Duplicate Transactions | group by item, branch, qty, price; count > 1 and span ≤ 20 min | Flags a sale and its return (115 + 30) as a duplicate; flags two lines of one document that differ only by expiry |
| Price Variance | 115 only; per (item, branch, docnumber) max/min `transprice` > 1.10 | min price ≈ 0 → ratio 9999 |
| Cost Fluctuations | per item, whole chain, all doccodes: max/min `newcostprice` > 1.20 | Mixes transfer costs, all branches, whole period → noisy |
| Stock Adjustments | doccode 50/150 grouped count + qty | No value, no user, no threshold |
| Items Frequently Stocked Out | `newqty = 0` on 115/125/150/180, medicine only, count per item+branch | No threshold vs sales rate |
| Overstock Items | stkbal `nowqty / monthlyqty` | Already covered by purchasing coverage screens |

---

## 3. What already exists — reuse, don't duplicate

| Need | Existing piece | How we use it |
|---|---|---|
| Doccode meanings | `apps/finance/queries/sybase_finance.py` (all 27 codes verified from live `transdoc`); `apps/stockcount/models.py` labels | One shared label map; no new lookup table |
| Reading `stktrans` from each node | `apps/stockcount/engine.py` (`fetch_transaction_items`, doccode + user filters); `config/sybase.py`; tiered fast/slow sync lanes in `apps/sync/tasks.py` | The ledger sync reuses the same connection + per-node retry pattern |
| Sales/returns lines | `customers.PurchaseHistoryLine` (cost at sale, list price, discounts, trans_time, softech_user) | **Not reused for the audit ledger** — see decision D1 |
| Below-cost logic | `apps/insights/rules.py::rule_below_cost_sale` (top-10 for the narrative report) | Moved into one shared helper both modules call, so "below cost" has one definition |
| Excluded channels / items | `forecasting.KpiResolver` (`nonexclude_channels`, `credit_channels`) + insights' excluded-item keywords | Same exclusion source for check 1 |
| Monthly sales rate | `catalog.ItemStock.monthly_qty` (stkbal `monthlyqty`) | Check 6 |
| Stock-count sessions | `stockcount.StockCountSession` / `StockCountSnapshot` (branch, items, snapshot_at, variance) | Check 11 |
| SOFTECH user → staff | `users.StaffProfile.erp_user` / `softech_user_id` | Every finding names the employee |
| Review lifecycle pattern | `audit.AbuseFlag` (open/reviewed/dismissed/escalated, reviewer, note) | Same statuses and wording |
| Audit of threshold changes | `audit.AuditLog.log()` | New action codes (§8) |
| Freshness bar + refresh button | `apps/sync/freshness.py` domains + `DataFreshnessBar` | New domain `stock_audit` |
| Overstock | Purchasing coverage / doc 22 screens | Check 7 is a **link only** |
| Grid keyboard, number inputs, branch labels | `useGridKeyboard`, `useNumberInputGuards`, `useBranchLabels` | Standard |

**Not reused, by decision:** `insights.InsightRule` holds one threshold per rule, has no branch override and
belongs to a period narrative report. Stock audit needs several parameters per rule, branch overrides
and findings with a review lifecycle. Stretching `InsightRule` to cover that would muddle both modules.

---

## 4. Decisions to approve

**D1 — A separate, lean ledger mirror `StockLedgerLine` for all doccodes (recommended)**
instead of adding columns to `PurchaseHistoryLine`.
- Why: the audit needs `newqty`, `storecode`, `docdate` vs `trans_time`, the per-line `usercode`, the return
  references (`r_doccode`/`r_docnumber`/`r_docdate`) and the transfer/adjustment doccodes.
  `PurchaseHistory` is a customer-purchase model (mandatory customer FK); it has no place for transfers and adjustments.
- Changing the sales sync that analytics, incentives, gamification and insights depend on carries more
  risk than storing sales lines twice.
- Size (measured in Phase 0): **536,957 rows in 180 days across all codes ≈ 3,000/day** (115 = 316k,
  10 = 67k, 125 = 62k, 25 = 60k). A 365-day window is about 1.1M rows.
- Alternative (not recommended): add `new_qty` + return references to `PurchaseHistoryLine` and mirror
  only non-sales codes into the ledger.

**D2 — New app `apps/stock_audit`.** It holds the ledger, rules, overrides, findings, engine, API and help content.
`apps/audit` stays the generic action trail.

**D3 — Branch working hours.** `Branch` has no hours today. Add `working_hours` (JSON per weekday:
`{"sat": ["09:00","24:00"], …, "fri": ["13:00","24:00"]}`) and `is_24h` (bool). Migration on our
own `branches` table only (not SOFTECH). Editable in the existing branch settings screen.

---

## 5. Data model (`apps/stock_audit`)

**`StockLedgerLine`** — read-only mirror, rolling **365 days** (setting `stock_audit_window_days`, owner decision 2026-10-26).
Natural key (docnumbers collide across branch/doctype — see memory "docnumber collisions"):
`(node_branch, branchcode, doccode, docnumber, docdate, itemcode, trans_time, line_seq)`, where `line_seq` is
the ordinal of identical rows inside one sync batch. Upsert by that key, so re-runs are idempotent.
Fields: `branchcode, storecode, doccode, docnumber, docdate (date), trans_time (datetime), itemcode → item FK,
transqty, transprice, transprice_total, newqty, newcostprice, itemsaleprice, itemsalestax, itemsaleprice_tax,
custdiscp, specialdiscp, pharmacydiscp, bonusqty, itemexpirydate, personcode, usercode, r_doccode,
r_docnumber, r_docdate, retqty, suppliercode`.
Indexes: `(branchcode, doccode, trans_time)`, `(item, branchcode, trans_time)`, `(usercode, trans_time)`,
`(branchcode, doccode, docnumber, docdate)`.

**`StockAuditRule`** — one row per check (`code` unique), seeded. `name_ar/en`, `enabled`,
`params` (JSON, schema per rule, validated server-side), `severity_tiers` (JSON: warning/critical cut-offs),
`description_ar/en`.

**`StockAuditRuleOverride`** — `(rule, branch)` unique; `enabled` (nullable = inherit), `params` (a partial
JSON that is merged over the defaults). Effective params = defaults ⊕ override.

**`StockAuditRun`** — one per engine run: window, nodes, rule versions (a params snapshot), row counts,
duration, error. It records which threshold values produced each finding.

**`StockAuditFinding`**
- `rule_code`, `dedup_key` (unique together), `severity`, `status` (open / reviewed / dismissed / escalated)
- `branch`, `item`, `doccode`, `docnumber`, `docdate`, `occurred_at`, `softech_user`, `staff` FK (resolved)
- `value_egp`, `metric` (the measured number), `threshold` (the effective value used), `evidence` (JSON: ledger line ids + key numbers)
- `first_run`, `last_run`, `first_seen`, `last_seen`
- `reviewed_by`, `reviewed_at`, `review_note`

Re-runs update `last_seen`/`metric`. A dismissed finding **stays dismissed** unless its value grows by more
than 50% (then it is reopened with a note). Findings are never deleted; they age out of the default view.

---

## 6. The checks (10 active; #8 dropped) — exact definitions and default thresholds

All values are editable chain-wide and per branch. EGP values are at **cost** unless stated otherwise.
"Line" = one `StockLedgerLine`.

| # | Code | Rule (deterministic) | Default params | Severity |
|---|---|---|---|---|
| 1 | `sale_below_cost` | doccode 115; **unit price net of VAT** = `transprice / (1 + additionaldiscp/100)` < `newcostprice` (§14 B). Loss % = (cost − price)/cost; loss EGP = (cost − price) × qty. **Excluded:** credit/contract channels and customers in the `excluded_personcodes` list (free packs), excluded items (insights keywords), qty ≤ 0 | `min_loss_pct=5`, `min_loss_egp=20`, `excluded_personcodes=['4785','4283']` | warning; **critical** ≥ 30% or ≥ 500 EGP (critical also requires the warning floors) |
| 2 | `duplicate_line` | Same branch, doccode, item, qty, price, and **same expiry**, on two lines whose `trans_time` differs by ≤ N min. Not a duplicate: a 115 and a 30 for the same item/qty (a correction); two lines of one document with different expiries | `window_min=20` | warning |
| 3 | `price_variance_invoice` | doccode 115; per (branch, docnumber, docdate, item): max/min unit price > ratio. Lines with unit price < floor ignored | `ratio=1.10`, `min_price_egp=1` | info; warning > 1.5 |
| 4 | `cost_fluctuation` | Purchase unit cost (doccode 10 net line cost) per (item, branch) vs the **previous** purchase of the same item at that branch within N days; change either way | `change_pct=20`, `lookback_days=90` | info; warning > 50% |
| 5 | `stock_adjustment` | doccodes 50 / 150 / 160 (configurable). Flag (item, branch) with ≥ K entries in N days, **or** a single entry ≥ V EGP. Always produces a per-user ranking (no flag needed) | `doccodes=[50,150,160]`, `count=3`, `days=30`, `single_egp=500` | warning; critical ≥ 2,000 EGP |
| 6 | `frequent_stockout` | `newqty = 0` after a 115/125/150/180 line; medicine (`medicine_type='10'`); count per (item, branch) in N days; only items with `monthly_qty` ≥ M | `count=3`, `days=30`, `min_monthly_qty=1` | info |
| 7 | `overstock` | **Link only** → existing purchasing coverage screen, pre-filtered to the branch | — | — |
| 8 | ~~`backdated_entry`~~ | **DROPPED** (owner decision 2026-10-26): it found 0 lines in 180 days because SOFTECH sets `docdate` at save time (§14 E). The number is kept, so the other checks keep their numbers | — | — |
| 9 | `after_hours_entry` | `trans_time` outside the branch's `working_hours` for that weekday, beyond a grace period. `is_24h` branches skipped. Optional doccode filter | `grace_min=30`, `doccodes=all` | info |
| 10 | `return_without_invoice` | doccode 30: (a) `r_docnumber` empty/0 → no invoice; (b) Σ returned qty for (branch, r_docnumber, r_docdate, item) > sold qty on that 115 invoice. **`r_doccode` is unreliable (0/blank), so matching always assumes 115** (§14 C). If the original is older than the ledger window, look it up once from SOFTECH (read-only) and cache it | — | warning; **critical** when over-returned |
| 11 | `adjustment_after_count` | A 50/150 line on an item covered by a stock-count session at that branch within H hours **after** `snapshot_at`, where the adjustment **does not match** the counted variance (different direction, or qty differs by > tolerance, or the item counted as OK). Posting the counted result is normal and is not flagged | `hours=48`, `qty_tolerance=0` | warning |

Notes:
- **Check 1 price basis — VERIFIED in Phase 0.** On sales lines `transprice` includes VAT, `additionaldiscp` holds
  the VAT rate (14) and `itemsalestax` is the VAT **amount** in the list price. `newcostprice` is the pre-VAT net
  purchase cost (purchase lines: `newcostprice = transprice` = net of discount, before VAT). So the price is
  divided by (1 + VAT rate) before it is compared with cost. The workbook compared the gross price, so it missed
  taxed lines sold between 100% and 114% of cost.
- **Check 11 limit.** Only counts recorded in our `stockcount` module are seen; counts done only inside
  SOFTECH are invisible.
- Every rule's code lives in `apps/stock_audit/rules.py`, one pure function per check, with unit tests on
  fixed fixtures.

---

## 7. Engine and scheduling

1. **Ledger sync** `sync_stock_ledger` — **from HQ only.** Phase 0 showed that HQ holds every branch's lines
   (branch 160: an exact match, 158,430 = 158,430; other nodes differ by ≤ 3 rows of replication lag). The sync is
   incremental by **`docdate` day boundary** (indexed; `trans_time` is not indexed), re-reading the last 2 days, so
   late rows are never missed. The upsert key keeps re-reads idempotent. Prune lines older than the window nightly.
2. **Engine** `run_stock_audit [--days N] [--rule CODE] [--branch X]` — loads effective params per branch,
   runs the enabled rules over the window, upserts findings, writes a `StockAuditRun`.
3. **Schedule** (APScheduler, gated by `STOCK_AUDIT_ENABLED`): ledger sync every 2 h during the day plus a
   catch-up at 03:00; engine after each sync.
4. **Refresh button** on the screen: a forced sync + run for the selected branches, with a progress bar.
5. Freshness domain `stock_audit` (last ledger sync per node, last engine run).

---

## 8. API (`/api/stock-audit/`)

| Endpoint | Purpose |
|---|---|
| `GET summary/` | Counts by check × severity × status, per branch; EGP totals |
| `GET findings/?rule=&branch=&status=&severity=&user=&item=&from=&to=` | Cursor-paginated list |
| `GET findings/{id}/` | Detail + evidence lines |
| `POST findings/{id}/review/` | `{status, note}`; note required for dismiss/escalate |
| `POST findings/bulk-review/` | Same, for selected ids |
| `GET by-user/` | Per SOFTECH user: findings + adjustment value (check 5 ranking) |
| `GET findings/export/` | Excel; branch names via BL, never bare codes |
| `GET/PUT rules/`, `GET/PUT rules/{code}/overrides/{branch}/` | Thresholds; params validated per schema |
| `POST refresh/` | Forced sync + run (async job id) |

New `AuditLog` actions: `stock_audit_rule_changed`, `stock_audit_override_changed`,
`stock_audit_finding_reviewed`, `stock_audit_finding_escalated` (old/new values in `changes`).

**Permissions** — new RBAC module `stock_audit`, enforced server-side:
- admin / supervisor / quality_manager: view all branches, review, export, edit thresholds (edit = admin + quality_manager).
- **Branch managers:** view + review **their own branches only** (scoped by `StaffProfile` branch access),
  owner decision 2026-10-26. Granted to **named users only**, not to the whole `pharmacist` role: a new
  `StockAuditAccess` row (staff, level = branch_manager, granted_by, granted_at, revoked_at) inside
  `apps/stock_audit` (no change to `users`), managed by admin on the settings tab, and every grant/revoke is
  written to `AuditLog`. **Shift managers:** maybe later, as a second `level` with the same branch scoping.
- Everyone else: none.

---

## 9. Screen `/stock-audit` (Arabic RTL, calm)

- **Top:** `DataFreshnessBar` (domain `stock_audit`) + refresh; filters: period, branch (multi), severity, status, user.
- **Tabs** (`useHelpTab`):
  1. «ملخص» — one card per check (open count, EGP, trend vs previous period), and a branch × check matrix; clicking opens the tab, already filtered.
  2. «المبيعات والأسعار» — checks 1, 2, 3, 4 (a check selector inside the tab).
  3. «تسويات المخزون» — checks 5 and 11 + per-user adjustment ranking.
  4. «توافر المخزون» — check 6 + a link to coverage/overstock (check 7).
  5. «التوقيت والإدخال» — check 9.
  6. «المرتجعات» — check 10.
  7. «الإعدادات» — thresholds: chain defaults, a branch-override column, "inherited" shown greyed;
     each save logged with before/after values.
- **Grid:** `useGridKeyboard` (↑↓ Space Enter, Ctrl+A); the row expands inline to show the evidence lines and
  the employee; review buttons (تمت المراجعة / تجاهل / تصعيد) sit inline with a short note field — no modal.
- Excel export per tab, keeping the current filters.
- Later: "View employee timeline" link → the monitoring investigation timeline.
- In-app help: `apps/help/content/stock_audit.py` (AR + EN), one section per tab and per check, with
  plain-language threshold explanations.

---

## 10. Notifications (optional, Phase 4)

A daily digest of **new critical** findings to quality manager + supervisor via `apps/notifications`
(dedup key per finding). There is no per-finding alert noise.

---

## 11. Tests

- One unit test per rule with fixtures for each false-positive case: free-pack customer, 115→30
  correction, split-expiry lines, near-zero price, 24 h branch, adjustment matching the count variance,
  original invoice outside the window.
- Override merge (defaults ⊕ branch), params schema validation, threshold changes audited.
- Idempotency: running the engine twice gives the same findings; a dismissed finding stays dismissed; it is
  reopened when its value grows.
- Ledger upsert key: colliding docnumbers on different branches/doccodes don't merge.
- Permissions: branch scoping, edit-thresholds role, export role.
- Workbook parity: run the rules on the Dec-2024 CSV week and compare counts with the workbook's
  sheets; every difference is explained by a documented exclusion.
- `test_help.py` passes for `/stock-audit`.

---

## 12. Delivery phases (each a separate approved batch)

| Phase | Content | Writes |
|---|---|---|
| **0 — Probe** (read-only) | Ledger row counts per node for 180 days; confirm VAT basis for check 1; confirm `r_docnumber` population on 30 lines; sample free-pack personcodes | none |
| **1 — Ledger** | `apps/stock_audit` + `StockLedgerLine` + `sync_stock_ledger` + freshness domain | Postgres only |
| **2 — Engine + thresholds** | Rules/overrides/runs/findings models, engine, checks 1, 2, 3, 5 + workbook parity test | Postgres only |
| **3 — Screen** | `/stock-audit` tabs, review workflow, settings tab, Excel, help | — |
| **4 — Remaining checks** | Branch working hours (D3), checks 4, 6, 9, 10, 11, link for 7, digest notification | Postgres only |
| **5 — Monitoring link** | Finding → employee investigation timeline | — |

---

## 13. Owner decisions and open questions

Answered 2026-10-26:
1. **Free packs (check 1):** exclude both 4785 «FREE PACKS NOVARTIS» and 4283 «ابونا بسطورس» (default
   `excluded_personcodes`, editable on the settings tab).
3. **Ledger window:** 365 days.
4. **Access:** management (admin / supervisor / quality manager) for all branches + branch managers for their
   own branches; shift managers maybe later.
6. **Check 8:** dropped.

4a. **Branch managers:** named users only (`StockAuditAccess`, §8).
5. **Check 5 doccodes:** 50 + 150 + 160 (write-off included).

Still open (not blocking Phases 1–3):
2. **Branch working hours** — per-weekday hours for each branch, and which branches are 24 h (needed by Phase 4, check 9).

---

## 14. Phase 0 probe results (2026-10-26, read-only)

Command: `python manage.py probe_stock_audit [--days 180] [--nodes] [--section A,B,C,D,E]`
(`apps/sync/management/commands/probe_stock_audit.py`; it forces `SOFTECH_READ_ONLY`, SELECT only). Raw output:
`docs/architecture/stock_audit_phase0_probe.txt`.

**A — Volume and source.** 536,957 lines in 180 days (≈ 3k/day), across HQ (100) and branches 130–170.
HQ is consolidated: branch 160's node has 158,430 lines and HQ has 158,430 for branchcode 160; the other
nodes differ by ≤ 3 rows. → Sync from HQ only; no per-node connections.

**B — VAT basis.** Taxed sales lines: `transprice` 45.00, `itemsalestax` 5.5263, `itemsaleprice_tax` 39.4737,
`additionaldiscp` 14, `newcostprice` 27.55. Purchase lines: `newcostprice = transprice` = net cost before VAT
(e.g. list 180 → pre-VAT 157.89 → −20% = 126.32). → Check 1 compares `transprice / (1 + additionaldiscp/100)`
with `newcostprice`.

**C — Returns.** 8,684 return lines in 180 days: `r_docnumber` filled on 8,678; empty on 6 (`r_doccode = -30`).
`r_doccode` is 0 or blank, not 115. In a 30-line sample, every referenced 115 line was found on the same
branch + docnumber + `r_docdate`, and the sold qty was available for comparison. → Check 10(a) will be rare;
10(b) works with an indexed lookup.

**D — Free-pack candidates** (≥ 80% of ≥ 5 sales lines below cost, 180 days):
4283 «ابونا بسطورس» — 838/876 lines below cost, 58,599 EGP; 4785 «FREE PACKS NOVARTIS» — 29/33 lines, 39,187 EGP.

**E — Volumes at the default thresholds (30 days, before exclusions, gross price).** Check 1: 151 lines
(160 = 110, HQ = 17, others ≤ 10). Check 8: **no line in 180 days has `trans_time` more than 1 day after `docdate`**.
Only 190 purchase lines differ by exactly 1 day, and none are future-dated. SOFTECH sets `docdate` at save time,
so this check cannot find anything. → Check 8 is on hold pending your decision (Q6).

**Bug found in passing — FIXED 2026-10-26:** `apps/batches/stock_expiry.py:63` called
`branch.effective_db_port()`, but it is a property → `'int' object is not callable` for every branch node, so the
FEFO stock-expiry mirror can only refresh HQ. Fixed (property passed, not called) with regression tests in `test_purchase_expiry_audit.py`; the first full sweep synced 6/6 nodes, 44,916 rows. Every earlier run had been HQ-only.

