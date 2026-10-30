# 01 — Module Inventory & Review Status

**Review started:** 2026-10-30 · **Method:** read-only code review of all 64 `apps/*` (routes `frontend/src/App.jsx`,
sidebar `frontend/src/components/Layout.jsx`, flags `config/settings.py`, jobs `apps/sync/tasks.py`) + read-only row
counts on the **office PostgreSQL instance** (the instance the scheduler ran on until 2026-10-28; production VPS not yet
cut over). No code, config, data or SOFTECH was touched.

**Stack verified:** Django 4.2.13, DRF 3.15.1, simplejwt 5.3.1, APScheduler 3.10.4, PostgreSQL (office PG16), React 18.2,
Vite 5. ~255k backend LOC (excl. migrations). SOFTECH = Sybase ASE via jConnect/jpype (`config/sybase.py`).

### How to read "adoption signal"
Counts are **office-instance rows** — they show what staff actually *created*, not what engines generated. Caveats:
staff may have used SOFTECH directly instead; production usage after cutover is not yet observable; `last_login` is not
updated by JWT login, so it cannot measure activity. **"30d"** = rows created 2026-09-30 → 2026-10-29.

### Conclusion codes
Keep · Optimize · Simplify · Extend · Merge · Retire · Insufficient evidence. All conclusions are **provisional** until
the module's decision batch is reviewed with the owner.

---

## A. Demand, availability & supply

| App | Purpose | Status (evidence) | Adoption signal (office DB) | Provisional conclusion | Review |
|---|---|---|---|---|---|
| purchasing | Demand engine, ISR / sales-rate / coverage / shortage-flag writebacks, transfer recs, phantom, spike | Implemented, 18k LOC, 82 routes; writer flags default OFF in settings but **ON in the office `.env`** (ISR, rate, coverage, auto-top-up, engine schedule); ~6 parallel replenishment/allocation engines | ISR pushes 14 (6/30d); rate pushes 18; **TransferRecommendation 527,841 pending / 1 approved / 7 rejected**; adoption KPI always 0 (`source_recommendation` never set) | Optimize + simplify (one stated authority per decision; retire unused recommender) | Batch 3 |
| procurement | PurchaseLine mirror (doc 10/120), supplier/buyer KPIs, FOC, segmentation, alerts | Implemented; refresh every 30 min — stalled when scheduler host slept (`procurement/refresh.py:3-12`) | 6 engine runs/30d; 21.5k alerts with no action workflow | Keep; consolidate the 4 supplier↔item mappings | Batch 3 |
| supply | Control tower: DemandSignal, availability inbox, supplier comparison, SupplyCase, WhatsApp branch requests | Implemented (doc 24); heaviest coupling | 727 signals/30d; 1,185 availability lines; **SupplyCase 745 → 11 fulfilled, 349 cancelled**; supplier orders leave as WhatsApp text/Excel, **no PurchaseOrder created** | Keep + extend (PO object, case age) | Batch 3 |
| shortage | Branch shortage lists + system-wide matcher/learning | Implemented; exports read SOFTECH live although a mirror exists | 7 lists, 84 items total; stock-check has no "create transfer" action | Merge list flow into supply; keep matcher | Batch 3 |
| transits | Doc-125 in-transit mirror, 125↔25 reconciliation, picking/stocking sheets | Implemented; TR linking by docnumber only (non-unique per memory) | 38k notes + 68k audit events/30d (automatic) | Keep; fix link key; **its alerts drive 87% of notification volume** | Batch 1/2 |
| transfers | Inter-branch transfer requests (request/approval; staff re-key into SOFTECH and type back doc number) | Implemented; ISR pushes are a parallel transfer path that bypasses it | 25 requests total, 2 in 30d | Simplify (decide ISR-driven vs request-driven) | Batch 2 |
| invoices | Supplier-invoice OCR → match → SOFTECH purchase/return writeback | Implemented; writer **ON in office `.env`**; live stock read on every grid load | 81 invoices (73 in 30d), 3 bundles; PO match starved (no POs) | Keep + optimize | Batch 3 |
| vision | OCR corpus + engine comparison; in-house model slot | Partial; model dir empty | 10 samples | Keep as cheap data collection | Batch 3 |
| composition | Active-ingredient parsing → pharmacist-approved molecule index → POS alternatives | Partial (Track B writeback planned) | 18.5k index rows; parse run 2026-08-24 only; review backlog unmeasured | Extend (prioritise review by lost-sale items) | Batch 6 |
| catalog | Item master, stock, barcodes, aliases, supplier links, safety flags | Implemented; live SOFTECH search fallback (cached + breaker) | Mirror 51.9k items; 412 aliases learned/30d | Keep | Batch 3 |

## B. Inventory accuracy, expiry & waste

| App | Purpose | Status | Adoption signal | Provisional conclusion | Review |
|---|---|---|---|---|---|
| batches | Near-expiry/FEFO, purchase-expiry audit, rebalance, markdown, disposal | Partial — `StockBatch`/FEFO path dead (no caller of `receive_from_invoice`), `near_expiry_scan` runs on an empty table; markdown OFF and chain-wide | 45k stkbalexpiry rows; 8 audit runs | **Simplify** (one expiry truth) + close outcome loop | Batch 2 |
| stockcount | Snapshot → count → variance → adjustment sheet | Implemented; live SOFTECH snapshot in request | 14 sessions total, **0 in 30d** | Optimize (cutoff netting, money value) | Batch 2 |
| stock_audit | Rule-based audit of SOFTECH stock transactions (doc 32) | Implemented, live since 2026-10-26 | **915 findings, all `open`**; "escalate" creates no task | Keep + route actions | Batch 2 |
| forecasting | Seasonality, item forecasts, KPI board, scenarios | Partial — `forecast_30d/90d` written nightly but **no consumer** | 14 runs/30d; KPI board used for targets | Keep KPI board; merge/retire item forecast | Batch 7 |
| insights | ~108 deterministic rules → WhatsApp narrative reports | Implemented, sends daily/weekly/monthly | 7.4k findings; findings have no status/owner | Simplify (route to owners) | Batch 7 |
| analytics | Sales/performance/inventory dashboards | Implemented; "capital tied" valued at **selling price** not cost (`analytics/views.py:1958`) | n/a (read-only) | Optimize | Batch 7 |
| dashboard | Home summary | Implemented; no waste/shrinkage tiles | n/a | Extend | Batch 7 |

## C. Sales, margin & customer value

| App | Purpose | Status | Adoption signal | Provisional conclusion | Review |
|---|---|---|---|---|---|
| pos_orders | Indirect POS → SOFTECH pending order | Built; **writer OFF** (`POS_WRITER_ENABLED=False`) so push is a dry run | 58 orders total, peak 43 in Aug, **0 since 2026-09-06** | Keep; adoption blocked by writer gate | Batch 4 |
| offers | Promotions engine | Preview live; execution + both SOFTECH channels OFF | 1 offer | Extend later; **safety exclusions first** | Batch 1/4 |
| discount_approvals | Price/discount change approval + replication audit | Implemented; SOFTECH write OFF | 33 requests; 9.7k replication gaps | Keep; add margin delta | Batch 4 |
| commerce | Quotations/retail invoices/allocation grids | Dormant (503 while `COMMERCE_DOCS_ENABLED` off) | 0 documents | Insufficient evidence → likely retire | Batch 4 |
| customers | CRM, segmentation, Customer-360, merge queue | Implemented; writes gated | Mirror 198k; nightly segmentation | Keep (single scoring source) | Batch 5 |
| loyalty | Points/tiers/rewards | Partial — **two ledgers** (SOFTECH `picpoints` vs Django `points_balance`); portal shows the Django one | 14 Django accounts | **Simplify** (SOFTECH single ledger) | Batch 4 |
| vouchers | Django OTP vouchers + SOFTECH gift coupons | Vouchers not linked to POS; coupons live | 11 vouchers (none since May); 10.8k coupon serials | Merge vouchers → offers; keep coupons | Batch 4 |
| referral | Customer referral codes/leads | Implemented; rewards land in invisible Django ledger | n/a (no rows found) | Insufficient evidence | Batch 4 |
| recommendations | FBT mining, customer recs, POS basket intel | Partial; no scheduled miner; **basket intel lacks customer-allergy filter** | 2 engine runs | Keep basket intel; fix safety | Batch 1/4 |
| product_experience | Product content/media/SEO | Implemented; not used by POS | 608 media rows | Simplify (content only) | Batch 4 |
| enrichment | AI-filled catalog fields with approval | Implemented; **auto-approves ≥0.90 confidence incl. clinical fields** | 1,334 suggestions, 658 approved | Optimize (exclude clinical) | Batch 1 |
| images | Product image search/approval | Implemented; scraping threads in web process | 870 jobs/30d | Keep | Batch 4 |
| portal | Customer self-service PWA | Implemented; shows wrong points ledger | n/a | Keep; fix ledger | Batch 5 |

## D. Customer service, demand capture & channels

| App | Purpose | Status | Adoption signal | Provisional conclusion | Review |
|---|---|---|---|---|---|
| reservations | Hold item for customer | Implemented | **54 total, none since 2026-07-01** | Merge with demand (one intake) | Batch 5 |
| demand | Lost-sales capture + SLA + recovery | Implemented; recovery self-reported | **3 records total** (June) | Keep as canonical intake; auto-attribute recovery | Batch 5 |
| followups | Chronic refill tasks + WhatsApp refill reminders | Partial — generation/auto-close unscheduled; auto-close reads the **stale `erp` mirror (last data 2026-04-30)**; sending OFF | 76.8k tasks, **all created May** | Simplify + fix data source | Batch 5 |
| chronic | Chronic classification + interaction/contraindication KB | Partial; KB (40 interactions, 35 contraindications) used only by recommendations | 331 chronic items | Merge generator into followups; govern KB | Batch 6 |
| callcenter | Call logging, cases, callbacks, transcripts | Implemented; can't convert call → demand | 647 calls; 451 transcripts (Oct 28–29) | Keep; extend | Batch 5 |
| delivery | Orders (from SOFTECH CRM), dispatch, rider app, CSAT | Implemented; **`sla_due_at` never written → SLA metrics empty** | 40.4k orders (mirror), 450/30d; 172 CSAT/30d | Keep; optimize metrics | Batch 5 |
| omni | Unified inbox/timeline/automations | Implemented; no capture action in inbox | 237 conversations/30d | Keep (single inbox) | Batch 5 |
| whatsapp | Meta Cloud API transport | Implemented; credentials empty by default | 2 conversations | Keep as transport; drop separate inbox | Batch 5 |
| pbx | Issabel AMI bridge | Partial; bridge not a deploy unit | 626 call sessions/30d | Insufficient evidence | Batch 5 |
| social | Messenger/IG/Telegram webhooks | Partial (TikTok 501) | 3 messages | Keep thin | Batch 5 |
| campaigns | WhatsApp campaigns | Partial; free-form sends to cold audiences; **no consent/suppression**; can target by chronic condition | 1 campaign | Simplify (central consent first) | Batch 1/5 |

## E. Insurance, replacement & finance

| App | Purpose | Status | Adoption signal | Provisional conclusion | Review |
|---|---|---|---|---|---|
| insurance | Motalba claims, invoices, reprice | Implemented, heavily used; reprice writer OFF; live Sybase in some views | 105 claims, 102k lines | Keep; optimize live reads | Batch 7 |
| replacement | بدل الروشتة case orchestration | Implemented (doc 25 header stale); posting OFF | 18.6k reconstructed cases | Keep; pilot posting (already planned) | Batch 7 |
| lineage | Document graph library | Partial (used by replacement only) | 57.9k refs | Keep as library | Batch 7 |
| finance | Finance hub + A/P reconciliation | Recon implemented (writer OFF); hub only P&L auto-synced, rest manual | 172.9k match candidates; 525 exceptions/30d | Keep recon; simplify hub | Batch 7 |
| cheques | Post-dated cheque planner | Standalone, free-text payee | 0 plans | Merge into finance/recon | Batch 7 |
| payments | External payments + bank-statement audit | Implemented, manual double entry | 0 rows found | Insufficient evidence | Batch 7 |

## F. People, capability & platform

| App | Purpose | Status | Adoption signal | Provisional conclusion | Review |
|---|---|---|---|---|---|
| incentives | Cash incentive programs (incl. supplier-sponsored) | Implemented; live Sybase in request; **no Rx/sensitive-class exclusion** | 2 programs (May); 32 sales targets | Keep + guardrails | Batch 6 |
| gamification | Points/levels/badges/champions/rewards | Implemented, ON; rewards gross profit with cash ×1.5; **no points for safety/training** | 33k point events/30d; 40 players | Keep; rebalance | Batch 6 |
| help | In-app help, tours, onboarding, quizzes, ask-the-system | Implemented (15k LOC + 21k content); **system-usage only, no pharmacy knowledge** | 34 help events | Keep; extend toward competency | Batch 6 |
| qa | Branch inspection checklists | Partial, mobile only, no reporting | 1 template, 0 inspections | Extend (cold chain, follow-up) | Batch 6 |
| hr | Leave/overtime/advances/permits | Implemented | 2 leave requests | Insufficient evidence | Batch 6 |
| tasks | Operational tasks + schedules | Implemented; **recurring schedules never run** (`run_due_schedules` has no caller) | 1 task | Optimize or merge | Batch 6 |
| approvals | Generic approval engine | Implemented; not used by pricing/replacement | 3 requests | Keep; consolidate others into it | Batch 6 |
| personal | /me dashboard from SOFTECH identity | Implemented; live SELECT per widget | 8 widgets, 2 claims | Simplify | Batch 6 |
| notifications | In-app/web push/chatter/announcements | Implemented; **no retention**; 1.69M rows | **399k in 30d; 0% read** | **Simplify** | Batch 1 |
| audit | AuditLog + abuse detection | Partial; detector unscheduled; no retention | 66k logs | Keep; schedule | Batch 8 |
| users | Staff, RBAC, ERP permission mirror, MFA | Implemented; RBAC middleware in `log` mode | 91 staff profiles | Keep; enforce at cutover (planned) | Batch 8 |
| config | Settings, dropdowns, heartbeat | Implemented | — | Keep | Batch 8 |
| branches | Branch master, working hours | Implemented | 14 branches | Keep | Batch 8 |
| erp | Legacy `stktrans` mirror (25/30/115/125) | **Dormant/stale** — `run_erp_sync` unscheduled, URLs unmounted, **data ends 2026-04-30**, still read by followups/callcenter/patient profile | 70.7k transactions | **Retire** (repoint readers to `PurchaseHistory`) | Batch 1/8 |
| sync | SOFTECH mirror + all scheduled jobs | Implemented; full 130k-row stock upsert every 5 min; no retry/alerting | 2.8k runs/30d | Optimize | Batch 8 |

---

## Module count check
64 entries under `apps/`: 62 functional apps above + `tests` (test suite) + `__pycache__`. **No app is silently
omitted.** First-pass code review completed for all six groups (A–F). "Review" column = the decision batch in which
the owner reviews that module's proposals (see `00_INDEX_AND_DECISION_LEDGER.md`).
