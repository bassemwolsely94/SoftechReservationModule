# Product & Operations Review — Index and Decision Ledger

An evidence-based review of every module against ElRezeiky's commercial, operational, clinical-quality and
staff-development goals. It started on 2026-10-30.

- **Discovery only.** Nothing here authorises implementation.
- **Approval of an idea ≠ authorisation to build it.**

## Documents

| # | Document | Covers (requested output) |
|---|---|---|
| 01 | [Module inventory](01_MODULE_INVENTORY.md) | (1) Every module, its status, adoption signal, conclusion, review batch |
| 02 | [Current-state findings](02_CURRENT_STATE_FINDINGS.md) | (2) Findings, (9) duplication and cross-module dependencies, technical and productivity performance, safety |
| 03 | [Data opportunity map](03_DATA_OPPORTUNITY_MAP.md) | (3) SOFTECH and data availability classes A–D |
| 04 | [Benchmark register](04_BENCHMARK_REGISTER.md) | (4) External sources, fact vs our state vs adaptation |
| 05 | [Proposal backlog](05_PROPOSAL_BACKLOG.md) | (5) Prioritised backlog, (8) KPI and pilot plan per card |
| 00 | This file | (6) Decision ledger |
| 06+ | Specifications | (7) One file per approved proposal, created only after approval |

**Relationship to existing docs:**
- Extends `docs/architecture/08_DUPLICATION_REPORT.md` and `10_FEATURE_INVENTORY.md`. It does not replace them.
- `docs/CURRENT_STATE_AND_GAPS.md` (2026-08, Commerce OS scope) is partly stale. The repeat-order, basket and offers
  items it lists as missing now exist.

## Review order (decision batches)

| Batch | Theme | Modules | Why this order |
|---|---|---|---|
| **1** | Foundations | safety guardrails, alerts, outcome measurement, usage telemetry, consent | Safety and compliance first. Without measurement, every later decision is guesswork |
| **2 (current)** | Expiry and stock cash (owner-chosen 2026-10-30) | batches, purchasing cash-optimization/توزيعة, catalog, procurement; stockcount/stock_audit later | Owner priority; measured open loops; cash in stock |
| 3 | Buying and replenishment | purchasing, procurement, supply, shortage, invoices, catalog, vision | Working capital; too many parallel engines |
| 4 | Sales and margin | pos_orders, offers, discount_approvals, loyalty, vouchers, referral, commerce, recommendations, product_experience, images | Revenue vs margin; POS writer gate |
| 5 | Customer service and retention | demand, reservations, followups, callcenter, delivery, omni, whatsapp, pbx, social, campaigns, customers, portal | Intake merge; refill (after P-03, P-05) |
| 6 | Staff capability and clinical quality | help, gamification, incentives, qa, chronic, composition, tasks, approvals, hr, personal | Competency, drug information, cold chain |
| 7 | Finance, cash and management reporting | finance, cheques, payments, insurance, replacement, lineage, analytics, dashboard, insights, forecasting | Cash, reporting truth |
| 8 | Platform | sync, notifications (rest), audit, users, config, branches, erp | Performance, retention, RBAC enforcement |

## Decision ledger

| Proposal | Decision | Conditions / changes requested | Dependencies | Evidence still needed | Spec status | Build authorised? |
|---|---|---|---|---|---|---|
| P-01 Safety guardrails | **Deferred** (2026-10-30, owner: "not needed currently") | — | Pharmacist owner for the class list | None for (a)(c)(d) | — | No |
| P-02 Alert reset | **Deferred** (2026-10-30) | — | Owner of stuck transfers | 20-transfer verification sample | — | No |
| P-03 Outcome matching | **Deferred** (2026-10-30) | — | None | Match window choice | — | No |
| P-04 Telemetry + retire dead paths | **Deferred** (2026-10-30) | — | Before VPS cutover | Owner confirmation of each retire item | — | No |
| P-05 Consent / PDPL | **Deferred** (2026-10-30) | — | Legal confirmation | PDPL deadline and obligations | — | No |

| P-26 One honest expiry number | **Approved for specification** (2026-10-30) | Store 110 = closed branch, must be zero; 102 write-off, 105 return candidates, 103 expired cosmetics; closed-store alert | — | Accountant's clean-up decision for 110 | Not started — after full review | No (owner: build after all discussions) |
| P-27 Dead-stock recovery (doc 22 step 2 + توزيعة lane) | **Approved for specification** | Owner confirms stock mostly sits, and moving it is the fix | Doc 30 phase B (ordered waves) | Stock-age source; sell-through after move | Not started | No |
| P-28 Near-expiry at-risk worklist + outcome | **Approved for specification** | Action order: return (window) → move → corner → loss | P-29 window rule | Pilot branches; units/FEFO check | Not started | No |
| P-29 Return-window calendar (was quarantine ageing) | **Approved for specification**; top of Batch 2 | Window −2/+1 months; Pharma Overseas + Ibn Sina self-entry with an immediate answer; acceptance history | — | Supplier entry-screen sample; other suppliers' windows; returns owner | Not started | No |

| P-30 Measured availability + "out here, in stock there" list | **Approved for specification** (2026-10-30) | List owners: HQ store specialists (network) + branch salespeople; pilot branch 160 | Ledger `newqty` verification | 20-sample check | — | No |
| P-31 Unordered / short delivery detector | **Approved for specification** (narrowed) | Order record = the exported order Excel; price check dropped | P-29 (return fast) | — | — | No |
| P-32 Consolidate replenishment authorities | **Approved for specification** (consolidate, not retire) | Nothing retired; TransferEngine → توزيعة wave; Phase E → P-34 | Doc 30 phase B | — | — | No |
| P-33 Supply-flow quick fixes | **Approved for specification** | "Create transfer" on both screen and WhatsApp paths | VPS cutover for (e) | — | — | No |
| P-34 Cash-budget, velocity-tiered cover | **Approved for specification** | Approved as revised. Tier values and the slow-item "order on demand" rule are confirmed at spec time. Chronic-patient items are never on-demand. Any coverage-writer change is a separate SOFTECH-write confirmation | P-30 (measure), P-27/29/31 (cash release); coverage writer = SOFTECH write | Tier values; on-demand rule for slow items | — | No |

| P-35 One margin basis + channel × branch board | **Approved for specification** (2026-10-30) | Adds delivery contribution (D.L.V. item 2: 13 EGP fee, 10 EGP rider; 50 EGP/day motorcycle minimum; branch-paid extras need capture) | Finance confirms the VAT basis | 20-invoice validation | — | No |
| P-36 Discount policy-breach report (read-only) | **Approved for specification** (2026-10-30) | Owner: no discretionary discount allowed, so above policy = breach; all branches | — | Expected-discount calc vs SOFTECH samples | — | No |
| P-37 Identified-sale rate + one loyalty ledger | **Approved for specification** (2026-10-30) | Skip allowed when rushed or single-staffed; yes to gamification and targets | P-05 (consent), once outbound starts | — | — | No |
| P-38 Offers & vouchers + go-live gate | **Approved for specification** (2026-10-30) | Promotions planned; gate required before the first promotion | **P-01(b) class exclusion (now a hard dependency)**; P-35; P-39 | — | — | No |
| P-39 POS go-live: 100% SOFTECH parity | **Approved for specification** (2026-10-30) | Parity suite across sale shapes; performance fixes; phased pilot | Cutover; stop-and-ask on every posting step | Pilot branch | — | No |

| P-40 13-week cash view | **Approved for specification** (2026-10-30) | Audience: all finance users + admins; measured contract settlement; supplier terms by category; early-pay foregone line | P-41, P-42 for completeness; P-34 budget | Fixed outflows input | — | No |
| P-41 Contract receivables tracker | **Approved for specification** (2026-10-30) | Reuse the customer side of the A/P–A/R engine; 4227 ≈44d, 4288 ≈42d measured | Agreed days per contract (finance entry) | Wider read-only check across all 38 contracts | — | No |
| P-42 Supplier terms by item category + early-pay opportunities | **Approved for specification** (2026-10-30) | Terms per supplier × category (local / imported / non-discounted); paid on time | — | Terms entry | — | No |
| P-43 Finance hub hygiene | **Approved for specification** (2026-10-30) | Keep and freshen the GP and expense pages; cash flow → P-40 | — | — | — | No |
| P-44 Full accounting module | **Deferred (owner: later)** | — | — | — | — | No |
| P-45 Insurance claim collection embedding | **Deferred (owner: later)** | — | P-41 meanwhile | — | — | No |

| P-46 Refill-due worklist + "did they buy" | **Approved for specification** (2026-10-30) | Call centre owns; replaces its manual selection; pharmacist review only for flagged categories | **P-05 consent / legal check (re-surfaced)**; P-03 method on PurchaseHistory | Who works the list; phone-number quality | — | No |
| P-47 One quick capture for "not available now" | **Approved for specification** (2026-10-30) | Not an adoption failure (pre-launch); replaces paper/WhatsApp; shows approved alternatives when short | — | — | — | No |
| P-48 Delivery: ride-level rider payout ledger + status auto-close | **Approved for specification** (2026-10-30) | Missed-fee flag demoted (companion orders; ≤14k/90d); rider app later | P-35 | — | — | No |
| P-49 Call centre reason + outcome | **Approved for specification** (2026-10-30) | CRM order auto-linked; availability → P-47 capture; 4 reasons | — | — | — | No |

| P-50 Reward safe, competent work | **Approved for specification** (2026-10-30) | Deactivate the 2 test programmes; Rx incentives allowed with an "approved by" guard + audit; add training/QA/fridge/refill points; no 50% target | — | — | — | No |
| P-51 Pharmacy competency lite | **Approved for specification** (2026-10-30) | Owners author now (HR/trainer later); mystery shopper yes; link-out references | — | — | — | No |
| P-52 Governed drug information | **Approved for specification** (2026-10-30) | Link-out to Drug Eye / Medscape / Drugs.com; re-source BNF rows; "AI — not reviewed" label (owner approved 2026-10-30) | — | — | — | No |
| P-53 EDA inspection readiness (fridge log + checklist + visit record) | **Approved for specification** (2026-10-30) | EDA always asks for the fridge log; visits ≈ monthly at random | — | EDA checklist items from the owners | — | No |
| P-01(a) customer-allergy basket filter | **Rejected / moot** (owner 2026-10-30) | Allergies are not documented per patient in Egypt | — | — | — | No |
| P-01(c) block AI auto-approval of clinical fields | **Rejected for now** (owner: mass data collection first) | Safeguard proposed instead inside P-52 | — | — | — | No |

| P-54 Cutover safety: switch table + single writer instance | **Approved for specification** (2026-10-30) | Owner: all 15 writers ON at go-live. **Stop-and-ask:** office + VPS both writing = double-post risk, so the office runs read-only (kill-switch) as the dev copy; `WRITER_INSTANCE` startup guard | Runbook §11 | Owner CONFIRMED office read-only (2026-10-30) | — | No |
| P-55 Alerts + transit receipt-sync bug fix | **Approved for specification** (2026-10-30) | **Root cause found:** 13,320 swallowed "connection closed" receipt checks → false "in transit" + alerts; 19/20 sampled have receipts in SOFTECH. Digest to branch manager + HQ coordinator | — | — | — | No |
| P-56 DB retention + sync health | **Approved for specification** (2026-10-30) | Keep last 10 runs + 1/month; `customers/0029` on the cutover list; reconnect-and-retry rule for all lanes | — | — | — | No |
| P-57 Usage telemetry | **Approved for specification** (2026-10-30) | Owner: product decisions **and** individual evaluation, so staff notice, admin/HR-only individual view, 12-month retention, never usage-only judgements | Go-live | PDPL employee-data check | — | No |

| P-58 EDA track-and-trace foundation (dormant) | **Approved — foundation, left unused** (owner 2026-10-30) | GS1 parse + PackCode/PackEvent on purchase and sale behind `TRACK_TRACE_ENABLED=False`; no EDA reporting until guideline 804/2025 is read | — | Guideline 804/2025; SOFTECH plans; 2D scanners | Spec written | Foundation yes, in principle; confirm with wave 0 |

**Wave-0 specification status (2026-10-30):** written. Spec files:
- [P-54](06_SPEC_P-54_cutover_single_writer.md) — **BUILT 2026-10-30 on owner go-ahead** (`config/writers.py` writer_allowed on all 24 gates, writer jobs unscheduled off-instance, startup guard in asgi/wsgi/runserver/run_scheduler, `/api/sync/writer-switches/` + /sync card). Committed e4984829. **Live in the office 2026-10-31:** the 11 duplicated `.env` keys were removed (backup `.env.bak-2026-10-31`), and the office is the writer instance (`WRITER_INSTANCE=True`, `SOFTECH_READ_ONLY=False`) until the VPS cutover. At cutover, switch the two: VPS `True`, office `False` — never both
- [P-55](06_SPEC_P-55_transit_sync_and_alerts.md) — Part A committed (ad89b6be); **Parts B–C BUILT 2026-10-30** (daily per-branch digest, `notification_routing`, 3-failures sync alert, notification retention). Clean-up run 2026-10-30: in transit ≥14 days 776 → **149**, `receipt_check_failed=0`
- [P-56](06_SPEC_P-56_retention_and_sync_health.md) — **BUILT 2026-10-30** (retention job 04:45, change-only stock upsert, stale runs, lane retry, manual-run skip, morning chain, `customers/0030`, slow-request log + /sync card)
- [P-57](06_SPEC_P-57_usage_telemetry.md) — **BUILT 2026-10-30** (ScreenView, beacon in both layouts, /audit «استخدام الشاشات», `post_usage_notice` to run at go-live)
- [P-43](06_SPEC_P-43_finance_freshness.md) — **BUILT 2026-10-30** (nightly 02:15 finance sync, 4 freshness domains, cash flow retired, /payments hidden)
- [P-58](06_SPEC_P-58_track_and_trace_foundation.md) — **BUILT dormant 2026-10-30** (`apps/catalog/gs1.py`, `apps/trace`, `/api/trace/parse|scan/`; `TRACK_TRACE_ENABLED=False`; no scan field on screens yet)

**Wave-1 specification status (2026-10-31):** written. Build authorised for **P-26 + P-29 only** (owner 2026-10-31);
the rest wait. Repo-only (no SOFTECH or database queries); every unverified fact is an open question or a read-only
check for the owner. Spec files:
- [P-26](06_SPEC_P-26_one_expiry_number.md) — **BUILT 2026-10-31** (`apps/batches/store_roles.py`,
  `StockExpiryBalance.store_role` + backfill `batches/0006`, live-only KPIs + `buckets`, second KPI row, dashboard tile
  «⏳ الصلاحية», `at_risk_by_branch` feeding `rule_near_expiry` and `forecasting._expiry_risk`, `near_expiry_scan`
  unscheduled, `QuarantineModal` removed). Store 110 excluded everywhere; no alert or clean-up export (owner decision).
  Found: the `/batches` "expired still in stock" card counted store 110; `forecasting._expiry_risk` read the empty
  `StockBatch` table, so expiry risk was always 0
- [P-29](06_SPEC_P-29_return_window_calendar.md) — **BUILT 2026-10-31** (`return_window.window_for`, `return_calendar.py`,
  `procurement.SupplierReturnPolicy` seeded 565 + 260 (`procurement/0011`), `ExpiryDisposalRecord` answer/ledger fields +
  `ReturnWindowMonthly` (`batches/0007`), `/api/batches/return-window/…`, `/batches` «📆 تقويم المرتجع», hourly
  `return_window_reconcile` from doc 120, 1st-of-month `return_window_digest` to the `purchasing` role, branch
  "send to HQ by" lines in the weekly worklist, `purchase_expiry` freshness domain, policy suppliers added to the
  purchase-expiry mirror). Lines = branch shelves + HQ live + 105; 102/103 not shown. Lead time 14 days
  (`return_window_branch_lead_days`). Still open: supplier entry-screen samples (`entry_layout`), other suppliers'
  windows, units check on doc 120 vs `stkbalexpiry`
- [P-31](06_SPEC_P-31_unordered_delivery_detector.md) — **revised 2026-10-31**: the order file is the demand pivot
  (`Total.الفرق-مطلوب/راكد`). Each pivot download is kept as a need sheet (`PivotSheetSnapshot`); doc-10 lines of the
  pilot suppliers are flagged `unordered` (on no sheet in 14 days) or `over` (above the sheet's gap); no bonus /
  short / price checks; no change to `SupplyDecision` or the supply engine. **BUILT 2026-10-31** (snapshot on every
  pivot download, `import_pivot_snapshot` for saved files, check after each purchases refresh + daily 09:10 with a
  digest to `purchasing`, /supply «استلام بدون طلب»; migrations purchasing 0041, procurement 0012/0013, notifications
  0037, audit 0016)
- [P-33](06_SPEC_P-33_supply_quick_fixes.md) — **(a), (c), (d), (e) BUILT 2026-10-31** (owner: "P-33 without retry";
  yes to the `IsrPush` field + constraint). (a) shortage stock check «تحليل التحويل» / «إنشاء مقترحات التحويل» →
  the WhatsApp path's linked ISR legs (`IsrPush.origin_shortage_list`, `purchasing/0040`; a list made from a WhatsApp
  request moves through that request; shortage drafts never supersede the daily route draft). (c) `apps/transits/
  linking.py` — link needs docnumber + both branches (+ match date ±3 d); ambiguous → no link + audit;
  `audit_transit_links [--commit]` repair command (owner runs once). (d) shortage supplier exports read
  `ItemSupplierLink` + `PurchaseLine`; live SOFTECH only when a mirror is stale; the file names the source.
  (e) runbook §11.8b 7-morning purchases check. **(b) hourly shortage-flag retry NOT built** (owner deferred)
- [P-41](06_SPEC_P-41_contract_receivables.md) — customer side limited to listed contracts (today's customer query would
  read all retail sales); SOFTECH's own allocations, no matching; `ar_contracts` freshness domain
- [P-42](06_SPEC_P-42_supplier_terms.md) — `SupplierTerm` per supplier × category, invoice slices, early-pay list
- [P-40](06_SPEC_P-40_13_week_cash_view.md) — `/finance/cash` from P-41 + P-42 + cheques + fixed outflows; low/base/high;
  `/finance/cashflow` redirects there
- **Owner decisions 2026-10-31** (written into each spec):
  - P-26: store 110 is excluded from everything; the alert and the clean-up export are dropped.
  - P-29: returns are owned by the HQ purchasing and replenishment specialists (`purchasing` role).
  - P-31: buyers send the demand pivot (`/purchasing` export, column `Total.الفرق-مطلوب/راكد`).
  - P-41: agreed days count from the month end.
  - P-42: "non-discounted" has no criteria, so it is dropped; terms are local / imported only.
  - P-40: weeks start Saturday. Cheque due date = `cheqdate` for `financialdoccode='20'` (read-only probe; `cheqcashdate` is empty on bank cheques).
- All three finance specs need `core/branch_scope.py` (security batch 5, not merged on this branch) before building

**Owner process rule (2026-10-30):** go through all recommendations first; building and development start after all
the discussions. Approved cards wait as "approved for specification" until the review is complete.

Batch 1 as a whole was deferred by the owner. These cards are not re-proposed unless they become a dependency of a
proposal the owner wants, or new evidence materially changes the case. Example: offers or campaigns being switched on
would make P-01 and P-05 relevant again.

Decisions available for each proposal: approve for specification · approve a limited pilot · modify · defer · reject ·
need more evidence. Rejected items are not reintroduced unless new evidence materially changes the case.

## Review status: COMPLETE (2026-10-30)
All 8 batches have been reviewed.

| Outcome | Proposals |
|---|---|
| **Approved for specification** | **30** |
| Deferred | P-02–P-05 (P-02/P-04 parts re-approved inside P-55/P-57), P-44, P-45 |
| Rejected | P-01(a), P-01(c) |

P-01(b) survives inside the P-38 gate.

**Next:**
1. Write a specification per approved proposal (`06_SPEC_P-xx_*.md`): scope, user journey, rules, data mapping,
   acceptance criteria, measurement.
2. **Ask for implementation authorisation per wave.**
3. Stop-and-ask items stay gated at build time:
   - P-34 coverage writes;
   - P-38 offers execution;
   - P-39 POS posting;
   - P-54 writer switch-on.

## Proposed build order (provisional; the owner decides)

| Wave | When | Proposals | Why first |
|---|---|---|---|
| **0 — cutover readiness** | Before / at VPS go-live | P-54 single writer + switch table · P-55 transit receipt-sync fix + alert digest · P-56 retention, sync health, `customers/0029` · P-57 usage telemetry · P-43 freshness badges | Safety (double post), a correct sync, usable alerts, and measurement from day 1 |
| **1 — cash, fast** | First weeks after go-live | P-29 return-window calendar · P-26 one expiry number · P-31 unordered-delivery detector · P-33 supply quick fixes · P-41 contract receivables · P-42 supplier terms · P-40 13-week cash view | Direct cash, mostly read-only, small to medium |
| **2 — stock and availability** | Next | P-27 dead-stock recovery · P-28 near-expiry worklist · P-30 measured availability · P-32 consolidate engines · P-34 tiered cover (report first) | Trapped cash → availability within the same budget |
| **3 — margin, service, people** | Then | P-35 margin basis · P-36 discount-breach report · P-37 identified sales · P-46 refill list · P-47 quick capture · P-48 rider ledger · P-49 call reasons · P-53 EDA readiness · P-50 rewards · P-52 drug-information governance | Visibility and service, mostly small |
| **4 — counter platform** | After waves 0–1 are stable | P-39 POS parity + phased go-live → P-38 promotions gate · P-51 competency pilot | Largest effort and highest financial-accuracy risk |

## Standing cautions found during discovery (not proposals; for the owner's awareness)
1. **Office `.env` turns 15 SOFTECH writers ON.** The owner decided (2026-10-30) that the VPS is the **only writer**
   with all 15 ON, and the **office runs read-only** as the development copy (P-54).
2. **PDPL deadline (reported ~1 Nov 2026)** and **EDA track-and-trace (local products since 1 Aug 2026).** Both need
   legal or vendor confirmation now, independent of this review.
3. **Server-side RBAC is still in `log` mode.** Enforcement at cutover is already planned.
