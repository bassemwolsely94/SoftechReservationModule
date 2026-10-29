# 32 — Stock Transactions Audit (تدقيق حركات المخزون)

**Status:** DESIGN APPROVED (D1, D2, D3) 2026-10-26 · Phase 0 probe DONE (§14) · **Phases 1–4 BUILT — all 9 active checks live** (§15–18). Optional later: daily digest of new critical findings; link to the monitoring timeline (Phase 5).
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

**D3 — Branch working hours.** **As built:** `is_24h` + `working_hours` (time windows, the same every day; a window
may apply to some doccodes only) on `BranchSettings` — our own per-branch config table — instead of `Branch`, which is
filled by the SOFTECH branch sync, so no synced table changes. Editable in Settings → branches (§18).

---

## 5. Data model (`apps/stock_audit`)

**`StockLedgerLine`** — read-only mirror, rolling **365 days** (`STOCK_AUDIT_WINDOW_DAYS`, owner decision 2026-10-26).
**BUILT (Phase 1).** `stktrans` has no line id, and two identical rows are two real lines, so there is no upsert
key: each sync **replaces whole `docdate` days** (delete + insert for `[d1, d2)` in one transaction). Re-runs are
idempotent, lines edited or deleted in SOFTECH inside the window are picked up, and a failed chunk keeps its old
rows. Documents are always identified by `(branchcode, doccode, docnumber, docdate)` (docnumbers collide across
branch/doctype). `docnumber`/`r_docnumber`/`s_docnumber` are stored as integers (SOFTECH `decimal(10,0)`).
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
| 2 | `duplicate_line` | **As built (§15):** (b) two documents of the same type, branch and customer with **identical line sets** (item, qty, price, expiry), the first entered ≤ N min before the others, documents with < `cross_doc_min_lines` lines ignored (single-item repeat sales are normal); skipped when one of the 115 copies was returned (correction). (a) the same line repeated inside one document is **off by default** (`include_same_document`) | `window_min=20`, `cross_doc_min_lines=2`, `include_same_document=false`, `doccodes=all` | warning |
| 3 | `price_variance_invoice` | doccode 115; per (branch, docnumber, docdate, item): max/min unit price > ratio. Lines with unit price < floor ignored | `ratio=1.10`, `min_price_egp=1` | info; warning > 1.5 |
| 4 | `cost_fluctuation` | **As built (§17):** purchase (10) unit cost vs the previous purchase of the same item at the same branch **from the same supplier**, in an earlier document within `lookback_days`; free-goods lines (`pharmacydiscp = 100`) and the بدل الروشتة virtual suppliers excluded | `change_pct=20`, `warning_pct=50`, `lookback_days=90`, `same_supplier_only=true`, `excluded_suppliers=[4469..4472]` | info; warning > 50% |
| 5 | `stock_adjustment` | doccodes 50 / 150 / 160 (configurable). Flag (item, branch) with ≥ K entries in N days, **or** a single entry ≥ V EGP. Always produces a per-user ranking (no flag needed) | `doccodes=[50,150,160]`, `count=3`, `days=30`, `single_egp=500` | warning; critical ≥ 2,000 EGP |
| 6 | `frequent_stockout` | `newqty = 0` after a 115/125/150/180 line; medicine (`medicine_type='10'`); count per (item, branch) in N days; only items with `monthly_qty` ≥ M | `count=3`, `days=30`, `min_monthly_qty=1` | info |
| 7 | `overstock` | **Link only** → existing purchasing coverage screen, pre-filtered to the branch | — | — |
| 8 | ~~`backdated_entry`~~ | **DROPPED** (owner decision 2026-10-26): it found 0 lines in 180 days because SOFTECH sets `docdate` at save time (§14 E). The number is kept, so the other checks keep their numbers | — | — |
| 9 | `after_hours_entry` | **As built (§18):** a document whose first line was entered outside its branch's `BranchSettings` hours (local time) by more than `grace_min`; one finding per document; a window may apply to some doccodes only; `is_24h` / no hours → not checked | `grace_min=30`, `warning_after_min=120`, `doccodes=all`, `excluded_users=[]` | info; warning > 2 h |
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
   by **`docdate` range** (index `stktrans_60` = docdate, doccode; `trans_time` is not indexed), in 7-day chunks
   that each replace their days. Command: `sync_stock_ledger [--days 3 | --backfill | --from --to]`.
2. **Engine** `run_stock_audit [--days N] [--rule CODE] [--branch X]` — loads effective params per branch,
   runs the enabled rules over the window, upserts findings, writes a `StockAuditRun`.
3. **Schedule** (APScheduler, gated by `STOCK_AUDIT_ENABLED`, BUILT): `stock_ledger_sync` every 2 h 08:10–22:10
   replaces the last 3 days; `stock_ledger_catchup` 03:15 replaces 7 days and prunes beyond the window. The engine
   (Phase 2) runs after each sync.
4. **Refresh button** on the screen: a forced sync + run for the selected branches, with a progress bar.
5. Freshness domain `stock_audit` (BUILT: reads `StockLedgerSyncRun`, 120-min cadence; Phase 2 adds the last engine run).

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
- Ledger day-replace (BUILT, `apps/tests/test_stock_audit_ledger.py`): idempotent re-runs, identical lines kept,
  SOFTECH deletions disappear, days outside the range untouched, failed chunk keeps old rows (partial), prune.
- Permissions: branch scoping, edit-thresholds role, export role.
- Workbook parity: run the rules on the Dec-2024 CSV week and compare counts with the workbook's
  sheets; every difference is explained by a documented exclusion.
- `test_help.py` passes for `/stock-audit`.

---

## 12. Delivery phases (each a separate approved batch)

| Phase | Content | Writes |
|---|---|---|
| **0 — Probe** (read-only) | Ledger row counts per node for 180 days; confirm VAT basis for check 1; confirm `r_docnumber` population on 30 lines; sample free-pack personcodes | none |
| **1 — Ledger** ✅ BUILT 2026-10-26 | `apps/stock_audit` + `StockLedgerLine` + `StockLedgerSyncRun` + `sync_stock_ledger` + scheduler + freshness domain | Postgres only |
| **2 — Engine + thresholds** ✅ BUILT 2026-10-26 | Rules/overrides/runs/findings models, engine, checks 1, 2, 3, 5, live comparison with the workbook rules (§15) | Postgres only |
| **3 — Screen** ✅ BUILT 2026-10-26 | API, `/stock-audit` (summary, sales & prices, adjustments + per-user ranking, settings), review workflow, branch overrides, `StockAuditAccess`, Excel, help | Postgres only |
| **4 — Remaining checks** ✅ BUILT 2026-10-26 | Branch working hours (D3, on `BranchSettings`), checks 4, 6, 9, 10, 11, link for 7 · digest notification not built | Postgres only |
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
2. **Branch working hours** — answered 2026-10-26 (§18).

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

---

## 15. Phase 2 as built (2026-10-26)

**Code:** `apps/stock_audit/rules.py` (pure checks + `RULES` registry with defaults and schemas),
`params.py` (validation, defaults ⊕ chain ⊕ branch merge, `ensure_rules`), `engine.py` (`run_stock_audit`),
command `run_stock_audit [--days 30] [--rule X] [--branch X] [--seed]`, migration `stock_audit/0002`.
The scheduler runs the engine right after every ledger sync (same `STOCK_AUDIT_ENABLED` switch).
The insights excluded-items settings are now one shared function, `insights.rules.analytics_excluded_items()`,
used by both modules. Tests: `apps/tests/test_stock_audit_engine.py` (rules, false-positive cases, params, lifecycle).

**Engine behaviour:**
- Findings are keyed `(rule_code, dedup_key)`; the key is built from the document, item, time and price, never from a
  ledger id (ids change when a day is replaced) and never from quantity (a quantity edited in SOFTECH updates the
  same finding). Candidates that share a key in one run (split-expiry lines of one invoice) are merged: values
  summed, highest severity kept.
- Re-runs refresh value, evidence and `last_seen`. They never change the review status, except that a dismissed
  finding whose value grows by more than 50% is reopened with a note.
- Check 1 uses the sales channel of the invoice from the sales mirror (`PurchaseHistory.sales_channel` →
  `ChannelBucketMap`) to skip the `credit` bucket (`excluded_channel_buckets`, editable).
- Check 5 reads its own `days` lookback (30), even when the engine window is shorter.
- Staff: `StaffProfile.softech_user_id` = SOFTECH usercode (58 of 114 users seen are linked today).

**First live run, last 30 days, compared with the workbook's own rules on the same lines:**

| Check | Workbook rule | Ours | Why |
|---|---|---|---|
| 1 Below cost | 594 lines | 106 (9 critical) · 7,693 EGP | 187 free-pack lines (4785, 4283) excluded; 5% / 20 EGP floors; **+76 lines found only because VAT is removed** |
| 2 Duplicates | 1,587 groups | 6 identical documents · 684 EGP | The workbook grouped any two sales of one item at one price within 20 min (ordinary repeat sales) |
| 3 Price variance | 4 | 4 | Same; no near-zero prices in this window |
| 5 Adjustments | (count + qty only) | 31 single entries ≥ 500 EGP (2 critical) · 28,156 EGP | No item reached 3 adjustments in 30 days |

**Check 2 change from the approved design.** Same-document repeats were 138 sales + 32 purchases in 30 days.
136 of 138 and 32 of 32 were saved in the same second, with stock falling one unit per line (e.g. 1429 → 1428).
That is SOFTECH saving an item scanned once per unit, not a double posting, so part (a) is off by default.
It can be switched on chain-wide or per branch (`include_same_document`).

---

## 16. Phase 3 as built (2026-10-26)

**API** `/api/stock-audit/` (`apps/stock_audit/views.py`, `urls.py`): `me`, `summary`, `findings` (+ detail,
`review`, `bulk-review` ≤ 500, `export` xlsx), `by-user`, `rules` (+ `PUT rules/<code>/`,
`PUT|DELETE rules/<code>/overrides/<branch>/`), `access` (+ `candidates`, `revoke`), `refresh` (background:
3-day ledger re-read + engine, one at a time), `runs`. Every rule is enforced in `apps/stock_audit/access.py`.

**Access (owner decision):**
| Who | Sees | Review | Export | Thresholds | Grants |
|---|---|---|---|---|---|
| admin | all branches | ✔ | ✔ | ✔ | ✔ |
| quality_manager (`stock_audit` view/approve/export/edit) | all | ✔ | ✔ | ✔ | — |
| supervisor (`stock_audit` view/approve/export) | all | ✔ | ✔ | — | — |
| named branch manager (`StockAuditAccess`, any role) | own branches only (home + extra) | ✔ | ✔ | — | — |
| everyone else | nothing (403) | | | | |

RBAC module `stock_audit` added (`users.MODULE_CHOICES`, `seed_permissions`); migration `stock_audit/0004` creates
only the stock_audit rows, so no other module's permissions change. `/api/auth/me/` carries `can_stock_audit`, which
shows the sidebar item to a named branch manager without opening it to every pharmacist.

**Review moves** (`StockAuditFinding.TRANSITIONS`): open → reviewed / dismissed / escalated; escalated → reviewed /
dismissed; reviewed → open; dismissed → open. A note is required for every move except → reviewed. Each move appends a
dated line to `review_note` and writes `AuditLog` (`stock_audit_finding_reviewed`). Threshold, override and access
changes write `stock_audit_rule_changed`, `stock_audit_override_changed`, `stock_audit_access_granted/revoked`.

**Screen** `/stock-audit` (`frontend/src/pages/StockAuditPage.jsx`), sidebar «المخزون → تدقيق حركات المخزون»:
freshness bar (`stock_audit`) + «🔄 تحديث الآن» (management); tabs «📊 ملخص» (cards per check vs previous period,
branch × check matrix that opens the filtered list), «🧾 المبيعات والأسعار» (checks 1–3), «⚖️ تسويات المخزون»
(check 5 + per-user ranking), «⚙️ الإعدادات» (chain thresholds, branch overrides — empty = same as chain — and,
for admin, named branch managers). Rows expand inline with the message, the original SOFTECH lines and the review
buttons; `useGridKeyboard` (↑↓, Space, Enter, Ctrl+A); bulk review; Excel with branch names.

**Help:** `apps/help/content/stock_audit.py` — module, finding workflow, journey «مراجعة يومية», 4 tabs, 15-step tour.

**Tests:** `apps/tests/test_stock_audit_api.py` (18): scoping per role and per named branch manager, sidebar flag,
review moves and notes, bulk review across branches, threshold edit/validation/override, grant/revoke, export
scoped with branch names, ranking, refresh.

---

## 17. Phase 4 as built (2026-10-26) — checks 4, 6, 10, 11

**Code:** four pure rules in `apps/stock_audit/rules.py`; `engine.build_context` now also supplies medicine items,
monthly rates and current stock (`catalog.ItemStock`), the sales and total returns behind each referenced invoice
(`_return_references`, from the mirror), and counted stock-count rows (`_counted_rows`, `stockcount.StockCountSnapshot`,
expiry audits excluded). A rule's lookback can start before the report window (`lookback_from: report_from`, check 4)
or count back from today (checks 5 and 6). Screen: checks 4 → «المبيعات والأسعار», 11 → «تسويات المخزون», new tabs
«📦 توافر المخزون» (6 + link to `/inventory` «📦 الفائض» for check 7) and «↩️ المرتجعات» (10). Help updated.

**Definitions as built:**
- **4** — see §6. Same supplier only by default; free goods and suppliers 4469–4472 excluded.
- **6** — `newqty = 0` after 115/125/150/180 on a medicine (`medicine_type = '10'`), ≥ 3 times in 30 days, rate ≥ 1/month;
  one finding per item per month; value 0 (info), current stock shown.
- **10** — (a) no `r_docnumber`; (b) item not on the referenced 115 invoice (`r_doccode` ignored, always 115);
  (c) Σ all returns against that invoice > sold qty (critical). A reference older than the mirror (365 days) is skipped.
- **11** — net 50/150 within 48 h after a count snapshot covering the item ≠ counted difference (counted − expected);
  posting exactly the counted difference is not flagged; an adjustment on an item that counted OK is.

**First live run (30 days):**

| Check | Findings | Note |
|---|---|---|
| 4 Cost fluctuation | 177 (16 warning) · 23,734 EGP | First run without the fixes: 739 — see below |
| 6 Frequent stock-outs | 279 (info) | ~46 per branch |
| 10 Returns | 3 (no invoice, all branch 130) | No over-returns in the window |
| 11 Adjustment ≠ count | 0 | Only one counted session exists in `stockcount` |

**Check 4 changes from the design, found on live data.** (1) SOFTECH writes free goods as a separate line with
`pharmacydiscp = 100` and a small **non-zero** price (the VAT on the free goods, e.g. 3.89), so "price > 0" did not
exclude them; every 400–600% "jump" was a normal line against a free-goods line. (2) Of the remaining 670 changes,
505 compared two different suppliers — e.g. a 50%-discount buy-back from 4069 against a 17% discount from 4883 — which is
the supplier price comparison screen's job, and many lines were from the بدل الروشتة virtual suppliers 4469–4472
(buy-backs, not supply). Same-supplier, without those: 178. Comparing cost relative to list price changed little
(168), so it was not added. Both switches are editable on the settings tab.

---

## 18. Check 9 and branch working hours (2026-10-26)

**Hours (owner, 2026-10-26)** — `BranchSettings.is_24h` + `working_hours` (list of windows, local time, every day;
`apps/branches/hours.py` validates and measures; editable in Settings → branches → «🕘 مواعيد العمل»; seeded by
`branches/0010`):

| Branch | Hours |
|---|---|
| 160 | 24 hours (not checked) |
| 130, 140, 150 | 08:00 – 01:00 |
| 170 | 08:00 – 00:30 |
| 100 (HQ) | warehouse 08:00 – 21:00 (normally until 18:00, overtime until 21:00 treated as normal) · call center 09:00 – 24:00 for doccodes **110, 125, 170** (transfers to branches + expense issues; owner-confirmed) |

The HQ call-center document list was confirmed by the owner on 2026-10-26: transfers to branches (110, 125) and
expense issues (170) only. Sales, returns and reservations at HQ follow the warehouse hours.

**Rule** `after_hours_entry`: the document's first line time vs the windows that apply to its doccode, ± `grace_min`
(30). One finding per document, value = Σ |qty| × cost. Warning beyond `warning_after_min` (120). `excluded_users`
lets admin accounts be left out (empty by default).

**First live run (30 days):** 61 documents (15 warning); 62 after the call-center list was narrowed (one HQ sale at 21:50). Branch 170: 44 (sales entered after 01:00; mostly users 1702
and 10). Branch 100: 16 night purchase batches by user 1509 «BASSEM» (e.g. 6 Oct, 03:12, 200-line documents — admin/IT
bulk work; add 1509 to `excluded_users` if it should not be audited). 130/140/150: none beyond the grace period.

